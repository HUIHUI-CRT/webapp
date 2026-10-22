"""身份门禁：进入网站先登记一个昵称，之后全站都用这个身份。

设计说明（重要）：
    这里**不做任何身份核验**——没有密码、没有账号表，用户输入什么名字就是
    什么名字。它解决的是「到处重复填名字」的体验问题，**不是安全边界**。
    任何拿到网址的人都能以任意昵称进入，因此不要把敏感内容放在本站。

为什么仍然用签名 Cookie 而不是 localStorage：
    1. WebSocket 握手由浏览器发起，JS 无法附加自定义头，但同源握手一定会带
       Cookie，这样 /ws 也能拿到身份，聊天不会显示成「访客123」；
    2. 签名保证名字在传输中不被意外篡改，也让服务端能识别「这是本站发出的
       身份」而不是随手伪造的字符串；
    3. HttpOnly 让页面脚本读不到它，减少 XSS 直接把身份偷走的机会。

Cookie 内容：``<base64url(昵称)>.<到期时间戳>.<HMAC 签名>``。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional
from urllib.parse import quote

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config

# Cookie 名称：只用 ASCII，避免不同浏览器对中文名的兼容问题
COOKIE_NAME = "webapp_identity"

# 昵称长度上限（与前端输入框保持一致）
NAME_MAX = 24

# 身份有效期：没有密码，让身份长期有效，除非主动「换个名字」
SESSION_DAYS = 30

# 无需身份即可访问的路径（登记页自身、样式、通用脚本、健康检查）
PUBLIC_PATHS = {
    "/api/health",      # 存活探针
    "/api/login",       # 提交昵称（登记身份）
    "/api/logout",      # 换个名字
    "/api/session",     # 查询当前身份
    "/login.html",      # 登记页
    "/js/login.js",     # 登记页脚本
    "/js/decor.js",     # 装饰脚本（花瓣），登记页也要用
    "/js/common.js",    # 通用工具库（登记页也要用它发请求）
}
PUBLIC_PREFIXES = ("/css/",)


# ------------------------------------------------------------------ 昵称处理
def normalize_name(raw: object) -> str:
    """规范化昵称：折叠空白、去掉首尾空格、限制长度。"""
    text = " ".join(str(raw or "").split())
    return text[:NAME_MAX]


# ------------------------------------------------------------------ 签名密钥
_secret_cache: Optional[bytes] = None


def _secret() -> bytes:
    """取签名密钥：优先环境变量，否则生成一次并落盘复用。"""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    if config.SECRET:
        _secret_cache = config.SECRET.encode("utf-8")
        return _secret_cache

    path = config.DATA_DIR / ".identity_secret"
    try:
        if path.exists():
            data = path.read_bytes().strip()
            if len(data) >= 32:
                _secret_cache = data
                return data
        config.ensure_dirs()
        fresh = secrets.token_bytes(48)
        path.write_bytes(fresh)
        _secret_cache = fresh
        return fresh
    except OSError:
        # 极端情况下（磁盘只读）退化为进程内随机密钥：重启后需要重新登记昵称
        _secret_cache = secrets.token_bytes(48)
        return _secret_cache


# ------------------------------------------------------------------ 令牌
def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(token: str) -> Optional[str]:
    padding = "=" * (-len(token) % 4)
    try:
        return base64.urlsafe_b64decode(token + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def make_token(name: str, now: Optional[float] = None) -> str:
    """生成身份令牌：``<b64(昵称)>.<到期时间戳>.<签名>``。"""
    expires = int((now if now is not None else time.time()) + SESSION_DAYS * 86400)
    payload = f"{_b64(name)}.{expires}"
    signature = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_token(token: Optional[str], now: Optional[float] = None) -> Optional[str]:
    """校验令牌，通过则返回昵称，否则返回 None。"""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    encoded, expires_raw, signature = parts
    try:
        expires = int(expires_raw)
    except ValueError:
        return None
    if expires < (now if now is not None else time.time()):
        return None

    payload = f"{encoded}.{expires_raw}"
    expected = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None

    name = _unb64(encoded)
    if not name:
        return None
    return normalize_name(name) or None


# ------------------------------------------------------------------ 读取身份
def cookie_token(scope: Scope) -> Optional[str]:
    """从 Cookie 头里取出身份令牌。"""
    for key, value in scope.get("headers", []):
        if key.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            name, _, raw = part.strip().partition("=")
            if name == COOKIE_NAME:
                return raw
    return None


def identity_from_scope(scope: Scope) -> Optional[str]:
    """从 ASGI scope 里解析出当前昵称。"""
    return verify_token(cookie_token(scope))


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


# ------------------------------------------------------------------ FastAPI 依赖
def current_user(request: Request) -> str:
    """在已登记身份的上下文里取当前昵称。

    ``request.state.user`` 由下面的中间件在通过后写入。
    """
    name = getattr(request.state, "user", None)
    if not name:
        raise HTTPException(status_code=401, detail="尚未登记昵称，请先访问 /login.html")
    return str(name)


# ------------------------------------------------------------------ 中间件
class IdentityMiddleware:
    """纯 ASGI 中间件：同时覆盖 HTTP 与 WebSocket。

    不能用 ``BaseHTTPMiddleware``：它看不到 ``scope['type'] == 'websocket'``，
    那样 ``/ws`` 就绕过了身份门禁，聊天里会出现没有名字的人。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        name = identity_from_scope(scope)

        if name:
            # 把身份挂到 scope 上，路由里 request.state.user / ws.state.user 可用
            scope.setdefault("state", {})["user"] = name

        if name or is_public_path(path):
            await self.app(scope, receive, send)
            return

        # ---- 尚未登记昵称 ----
        if scope["type"] == "websocket":
            # 握手阶段直接关闭：前端会被送回登记页
            await send({"type": "websocket.close", "code": 1008})
            return

        if path.startswith("/api/"):
            response = JSONResponse(
                {"detail": "尚未登记昵称，请先访问 /login.html", "login_url": "/login.html"},
                status_code=401,
            )
        else:
            target = path
            query = scope.get("query_string", b"").decode("latin-1")
            if query:
                target = f"{path}?{query}"
            response = RedirectResponse(f"/login.html?next={quote(target, safe='')}", status_code=302)

        await response(scope, receive, send)
