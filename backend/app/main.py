"""FastAPI 应用入口：把四个模块组装成一个 HTTP + WebSocket 服务。

    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

一次 HTTP 请求在这份文件里的流转顺序（细节见 docs/代码导读.md）：

    ① Uvicorn 收到 TCP 连接并把请求交给 ASGI 应用（本文件的 ``app``）
    ② CORSMiddleware 处理跨域头（见下方 add_middleware）
    ③ 按注册顺序做路由匹配：/api/posts* → /api/files* → /api/upload →
       /api/download/* → /api/health 等运维接口 → 最后才是静态文件挂载
    ④ 命中业务路由则执行 routers/ 下对应的处理函数（携带 db 依赖）
    ⑤ 全部不命中时落到最后的 StaticFiles，用 frontend/ 目录里的文件应答

路由注册顺序是硬约束：``app.mount("/", StaticFiles(...))`` 必须放在最后，
否则它会抢先匹配并吞掉所有 /api 请求（对应计划书风险表中的「静态文件路由冲突」）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config
from .auth import COOKIE_NAME, SESSION_DAYS, IdentityMiddleware, identity_from_scope, make_token, normalize_name
from .db import init_db
from .ext import status as ext_status, reload_extension
from .routers import blog, files, workspace, ws
from .schemas import HealthInfo, IdentityInfo, IdentityRequest, LoginResult, SessionInfo
from .services import hub

# ---------------------------------------------------------------- 日志格式
# 每条日志形如：2026-10-14 11:25:13,677 | INFO | webapp | 数据目录: ...
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("webapp")


# ---------------------------------------------------------------- 生命周期
@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动 / 停止时执行一次的准备工作。

    启动：建目录、建表、打印配置与 C++ 扩展状态（HTTP 端口由此确认）。
    停止：只记录数据位置，SQLite 与上传文件本身已经落盘。
    """
    config.ensure_dirs()
    init_db()
    info = config.describe()
    logger.info("数据目录: %s", info["db_path"])
    logger.info("上传目录: %s", info["upload_dir"])
    ext = ext_status()
    logger.info("C++ 扩展: %s (%s)", ext["engine"], ext["detail"])
    logger.info("监听配置: %s:%s（命令行 --host/--port 可覆盖）", info["host"], info["port"])
    logger.info("身份模式: 昵称门禁（无密码，昵称 %s 天有效）", SESSION_DAYS)
    logger.warning("提醒：本站不做身份核验，任何拿到网址的人都能以任意昵称进入。")
    yield
    logger.info("服务已停止，数据保存在 %s", info["db_path"])


# ---------------------------------------------------------------- 应用实例
app = FastAPI(
    title="多功能网站",
    description="博客 / 文件共享 / 在线聊天 / 共享画布 —— 本地可部署的一体化服务",
    version=__version__,
    lifespan=lifespan,
)

# 身份门禁中间件：必须先于业务路由注册，且覆盖 WebSocket（纯 ASGI 实现）。
# 注意 add_middleware 是「后添加的在外层」，所以下面 CORS 会包在它外面，
# 这样预检请求（OPTIONS）由 CORS 直接应答，不会被身份检查挡住。
app.add_middleware(IdentityMiddleware)

# 跨域中间件：默认放开（本地工具类应用），外网部署可设 APP_CORS_ORIGINS 收紧。
# 前端与接口同源，这里主要是为将来拆分前端做准备；Cookie 认证依赖同源，
# 因此不开启 allow_credentials。
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ 业务路由
# ①②③④ 中的业务部分：三个 router 各自带自己的 prefix，注册后统一参与匹配。
app.include_router(blog.router)   # /api/posts*            -> routers/blog.py
app.include_router(files.router)  # /api/files* /api/upload -> routers/files.py
app.include_router(ws.router)     # /ws（WebSocket 升级）   -> routers/ws.py
app.include_router(workspace.router)  # /api/tasks /api/polls /api/search 等协作 API


# ------------------------------------------------------------------ 身份接口
# 这三个接口在 auth.PUBLIC_PATHS 里，未登记昵称也能访问（否则无法完成登记）。

@app.post("/api/login", response_model=LoginResult, tags=["auth"], summary="登记昵称")
def login(payload: IdentityRequest, response: Response) -> LoginResult:
    """POST /api/login —— 登记一个昵称，之后全站都用它标识身份。

    这里**不做任何核验**：没有密码，输入什么名字就是什么名字。
    昵称只用于区分「谁说的、谁做的」，不构成安全边界。

    Cookie 为 HttpOnly + SameSite=Lax：JS 读不到、跨站请求不会带，
    有效期 30 天，换名字只需再调一次本接口。
    """
    name = normalize_name(payload.username)
    if not name:
        raise HTTPException(status_code=422, detail="昵称不能为空")

    ttl = SESSION_DAYS * 86400
    response.set_cookie(
        key=COOKIE_NAME,
        value=make_token(name),
        max_age=ttl,
        httponly=True,
        samesite="lax",
        # 经 Cloudflare 隧道访问时是 https，但本机调试是 http；
        # 这里不设 secure，保证两种场景都能登记（Cookie 里没有敏感信息）。
        secure=False,
        path="/",
    )
    return LoginResult(ok=True, user=IdentityInfo(name=name), expires_in=ttl)


@app.post("/api/logout", tags=["auth"], summary="换个昵称")
def logout(response: Response) -> dict:
    """POST /api/logout —— 删除身份 Cookie，下次进入时需要重新登记昵称。"""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "detail": "已退出，下次进入需要重新登记昵称"}


@app.get("/api/session", response_model=SessionInfo, tags=["auth"], summary="查询当前身份")
def session(request: Request) -> SessionInfo:
    """GET /api/session —— 前端据此显示当前昵称，或在未登记时跳转登记页。"""
    name = identity_from_scope(request.scope)
    return SessionInfo(
        authenticated=bool(name),
        user=IdentityInfo(name=name) if name else None,
        session_days=SESSION_DAYS,
    )


# ------------------------------------------------------------------ 运维接口
@app.get("/api/health", response_model=HealthInfo, tags=["system"], summary="健康检查")
def health() -> HealthInfo:
    """GET /api/health —— 首页用它判断「服务正常」并显示 C++ 扩展状态。

    这是纯内存计算，不碰数据库，因此也适合做存活探针。
    """
    ext = ext_status()
    return HealthInfo(
        status="ok",
        version=__version__,
        modules=["blog", "files", "chat", "canvas", "tasks", "polls", "search"],
        cpp_extension=ext["engine"],
        cpp_available=bool(ext["available"]),
    )


@app.get("/api/ext", tags=["system"], summary="C++ 扩展状态")
def ext_info() -> dict:
    """GET /api/ext —— 返回当前哈希引擎是 cpp 还是 python（files 页顶部提示用）。"""
    return ext_status()


@app.post("/api/ext/reload", tags=["system"], summary="重新加载 C++ 扩展")
def ext_reload() -> dict:
    """POST /api/ext/reload —— 编译完扩展后无需重启即可热加载。"""
    available = reload_extension()
    return {"reloaded": True, "available": available, **ext_status()}


@app.get("/api/rooms", tags=["system"], summary="实时房间状态")
def rooms() -> dict:
    """GET /api/rooms —— 读取内存中的聊天/画布房间与连接数（首页每 5 秒轮询）。"""
    return hub.stats()


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """GET / —— 307 跳转到 /index.html，保证根地址也能打开首页。"""
    return RedirectResponse(url="/index.html")


# ------------------------------------------------------------------ 静态前端
# ⑤ 必须放在最后：StaticFiles 挂载在 "/" 会兜住所有未被上面路由匹配的路径。
# 它直接以 frontend/ 为根目录对外提供文件，例如：
#   GET /index.html  -> frontend/index.html
#   GET /js/common.js -> frontend/js/common.js
# html=True 让目录请求自动回落到 index.html。


class NoCacheStaticFiles(StaticFiles):
    """页面与脚本一律禁止浏览器/中间层缓存，每次都必须回源取最新版本。

    为什么必须这样：本项目前后端同源、接口形态会随版本变化。一旦浏览器
    缓存了旧版 HTML/JS，就会出现「页面是旧的、接口是新的」的错配——
    典型故障是旧登录页读到新 /api/session（没有 auth_enabled 字段）后
    误判为「服务端没设口令」，自动跳转又被拦回来，形成无限重定向，
    用户看到的就是「卡在登录页、输入也没反应」。

    HTML 用 ``no-store``（连落盘都不允许），JS/CSS 用 ``no-cache``
    （允许存但必须每次用 ETag 回源校验，命中时返回 304，省流量）。
    """

    _NO_STORE_SUFFIX = (".html",)
    _REVALIDATE_SUFFIX = (".js", ".css", ".json")

    async def get_response(self, path, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        content_type = response.headers.get("content-type", "")
        if path.endswith(self._NO_STORE_SUFFIX) or content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        elif path.endswith(self._REVALIDATE_SUFFIX):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


if config.FRONTEND_DIR.is_dir():
    app.mount(
        "/",
        NoCacheStaticFiles(directory=str(config.FRONTEND_DIR), html=True),
        name="frontend",
    )
else:  # pragma: no cover - 仅在目录缺失时触发
    logger.warning("前端目录不存在: %s", config.FRONTEND_DIR)


def run() -> None:  # 便于 `python -m backend.app.main`
    """以脚本方式启动开发服务器（等价于命令行 uvicorn）。"""
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.RELOAD,
    )


if __name__ == "__main__":
    run()
