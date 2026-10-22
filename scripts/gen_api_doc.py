"""生成 HTTP / WebSocket 接口清单文档（docs/接口清单.md）。

为什么要自动生成：接口的「文件位置 + 行号」会随着代码增删注释而变化，
手写文档必然过期。这里直接读取运行中的 FastAPI 应用对象，反射出每个路由的
处理函数并定位到源码行，再把前端调用方一并扫出来。

用法（在项目根目录）：
    .venv\\Scripts\\python.exe scripts\\gen_api_doc.py
    # 也可指定输出：... scripts\\gen_api_doc.py docs\\其它名字.md
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402

JS_DIR = ROOT / "frontend" / "js"


# ------------------------------------------------------------------ 路由遍历
def iter_routes(routes: Iterable) -> Iterator:
    """展开 FastAPI 0.143 的嵌套路由结构。

    ``app.include_router(...)`` 注册出来的是 ``_IncludedRouter`` 包一层，
    真正的路由挂在它的 ``original_router`` 上，这里递归展开成平铺列表。
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None and hasattr(original, "routes"):
            yield from iter_routes(original.routes)
        else:
            yield route


def route_kind(route) -> str:
    """判定路由类型：http / ws / mount / other。"""
    name = type(route).__name__
    if name == "Mount":
        return "mount"
    if "WebSocket" in name:
        return "ws"
    if getattr(route, "methods", None):
        return "http"
    return "other"


def source_of(endpoint) -> str:
    """返回处理函数所在的「相对路径:行号」，例如 backend/app/routers/blog.py:46。"""
    try:
        path = inspect.getsourcefile(endpoint) or inspect.getfile(endpoint)
        line = inspect.getsourcelines(endpoint)[1]
    except (OSError, TypeError):
        return "-"
    try:
        rel = Path(path).resolve().relative_to(ROOT)
    except ValueError:
        rel = Path(path)
    return f"{rel.as_posix()}:{line}"


def summary_of(route, endpoint) -> str:
    """优先用路由声明的 summary，其次是处理函数 docstring 的第一行。"""
    summary = getattr(route, "summary", None)
    if summary:
        return str(summary).replace("|", "/")
    doc = inspect.getdoc(endpoint) or ""
    first = doc.strip().splitlines()[0] if doc.strip() else ""
    return first.replace("|", "/") or "-"


# ------------------------------------------------------------ 前端调用方扫描
def frontend_callers(path: str) -> str:
    """在 frontend/js/*.js 里找出引用了该路径的文件。

    路径参数（{post_id} 之类）会被截掉再匹配，例如 ``/api/posts/{post_id}``
    用 ``/api/posts`` 去搜，因此能同时命中列表与详情的调用。

    common.js 被排除：它是所有页面共用的 HTTP 客户端封装（api.get/post/...），
    只定义调用方式而不调用具体接口，列进来会污染「调用方」这一列。
    """
    probe = path.split("{")[0].rstrip("/")
    if not probe or not JS_DIR.is_dir():
        return ""
    hits: List[str] = []
    for js_file in sorted(JS_DIR.glob("*.js")):
        if js_file.name == "common.js":
            continue
        try:
            text = js_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if probe in text:
            hits.append(f"`frontend/js/{js_file.name}`")
    return "、".join(hits)


def is_framework_route(endpoint) -> bool:
    """判断是否为框架内置路由（/docs、/openapi.json 等）。

    它们的处理函数定义在已安装的 FastAPI 包里，对本项目的阅读没有意义，
    因此从接口表中剔除，只在文档末尾的前缀清单里提一句。
    """
    try:
        path = Path(inspect.getsourcefile(endpoint) or "").resolve()
    except (OSError, TypeError):
        return False
    return ".venv" in path.parts or "site-packages" in path.parts


# ------------------------------------------------------------------ 生成文档
def build_markdown() -> str:
    http_rows: List[Tuple[str, str, str, str, str, str]] = []
    ws_rows: List[Tuple[str, str, str, str]] = []
    mounts: List = []

    for route in iter_routes(app.routes):
        kind = route_kind(route)
        path = getattr(route, "path", "?") or "/"
        endpoint = getattr(route, "endpoint", None)

        if kind == "mount":
            mounts.append(route)
            continue
        if endpoint is None:
            continue
        if is_framework_route(endpoint):
            continue  # /docs、/openapi.json 等框架内置路由不进表
        if kind == "http":
            # HEAD 多为 GET 的自动伴随方法，文档里只保留主方法
            methods = sorted(set(route.methods) - {"HEAD"})
            if not methods:
                continue
            http_rows.append((
                "/".join(methods),
                path,
                getattr(endpoint, "__name__", "?"),
                source_of(endpoint),
                summary_of(route, endpoint),
                frontend_callers(path),
            ))
        elif kind == "ws":
            ws_rows.append((
                path,
                getattr(endpoint, "__name__", "?"),
                source_of(endpoint),
                summary_of(route, endpoint),
            ))

    # 让文档顺序与「阅读顺序」一致：博客 -> 文件 -> 系统 -> 小组协作 -> 认证
    order = ["/api/posts", "/api/files", "/api/upload", "/api/download", "/api/health",
             "/api/ext", "/api/rooms", "/api/tasks", "/api/polls", "/api/activity",
             "/api/stats", "/api/search", "/api/login", "/api/logout", "/api/session",
             "/", "/docs", "/openapi.json", "/redoc"]
    def sort_key(row):
        for index, prefix in enumerate(order):
            if row[1].startswith(prefix):
                return (index, row[1])
        return (len(order), row[1])
    http_rows.sort(key=sort_key)

    lines: List[str] = []
    add = lines.append

    add("# 接口清单（自动生成）")
    add("")
    add("> 本文件由 `scripts/gen_api_doc.py` 读取运行中的 FastAPI 应用生成，**请勿手工修改**。")
    add("> 代码变动后重新生成：")
    add(">")
    add("> ```powershell")
    add("> .\\.venv\\Scripts\\python.exe scripts\\gen_api_doc.py")
    add("> ```")
    add("")
    add("「位置」一列是处理函数的定义处（相对项目根目录的 `文件:行号`），")
    add("点击路径可直达该接口的交互式文档：`http://127.0.0.1:8000/docs`。")
    add("")

    add("## 1. HTTP 接口")
    add("")
    add("| 方法 | 路径 | 处理函数 | 位置 | 说明 | 前端调用方 |")
    add("|---|---|---|---|---|---|")
    for method, path, func, location, summary, callers in http_rows:
        add(f"| `{method}` | `{path}` | `{func}` | `{location}` | {summary} | {callers or '—'} |")
    add("")

    add("## 2. WebSocket 端点")
    add("")
    if ws_rows:
        add("| 路径 | 处理函数 | 位置 | 说明 |")
        add("|---|---|---|---|")
        for path, func, location, summary in ws_rows:
            add(f"| `{path}` | `{func}` | `{location}` | {summary} |")
    else:
        add("（无）")
    add("")
    add("握手时的查询参数：`?user=<昵称>&room=<房间>`；建立连接后改用 JSON 帧通信，")
    add("协议细节见 `backend/app/routers/ws.py` 文件头注释。")
    add("")

    add("## 3. 静态文件挂载")
    add("")
    for route in mounts:
        name = getattr(route, "name", "?")
        add(f"- 挂载点 `\"/\"`（name=`{name}`）：把 `frontend/` 目录整体对外提供，")
        add("  例如 `GET /index.html` → `frontend/index.html`、`GET /js/common.js` → `frontend/js/common.js`。")
        add("  它注册在所有 API 路由之后，未命中 `/api` 的请求才会落到这里。")
    add("")
    add("前缀匹配清单（同一台服务器、同一个端口）：")
    add("")
    add("| 路径前缀 | 归属 | 处理文件 |")
    add("|---|---|---|")
    add("| `/api/posts*` | 博客 | `backend/app/routers/blog.py` |")
    add("| `/api/files*`、`/api/upload`、`/api/download/*` | 文件 | `backend/app/routers/files.py` |")
    add("| `/api/tasks*`、`/api/polls*`、`/api/activity`、`/api/stats`、`/api/search` | 小组协作 | `backend/app/routers/workspace.py` |")
    add("| `/api/health`、`/api/ext*`、`/api/rooms` | 运维 | `backend/app/main.py` |")
    add("| `/ws` | 聊天 + 画布 | `backend/app/routers/ws.py` |")
    add("| `/docs`、`/openapi.json`、`/redoc` | FastAPI 自动文档 | 框架内置 |")
    add("| 其余全部 | 前端静态页面 | `frontend/` |")
    add("")

    return "\n".join(lines)


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "接口清单.md"
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_markdown(), encoding="utf-8")
    print(f"已生成 {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
