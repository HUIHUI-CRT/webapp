"""端到端冒烟测试：对一个正在运行的服务实例做真实 HTTP / WebSocket 验证。

用法：
    .venv\\Scripts\\python.exe scripts\\smoke_test.py [base_url] [nickname]

    base_url  默认 http://127.0.0.1:8000（也可以传隧道地址做公网验证）
    nickname  登记用的昵称，默认「冒烟测试员」；也可用环境变量 SMOKE_NAME 指定

示例：
    .venv\\Scripts\\python.exe scripts\\smoke_test.py
    .venv\\Scripts\\python.exe scripts\\smoke_test.py https://xxx.trycloudflare.com 小林
"""

from __future__ import annotations

import asyncio
import hashlib
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
NAME = (
    sys.argv[2] if len(sys.argv) > 2
    else os.getenv("SMOKE_NAME") or "冒烟测试员"
)
WS = BASE.replace("https://", "wss://").replace("http://", "ws://")

# Windows 控制台默认是 GBK，先切到 UTF-8，避免中文与符号输出报错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

passed = 0
failed: list[str] = []

# 带 Cookie 的会话：登录后所有请求自动携带会话 Cookie
JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
# 不带 Cookie 的「匿名」客户端，用来验证未登录确实被拦住
ANON = urllib.request.build_opener()


def check(label: str, ok: bool, extra: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"  [OK]   {label} {extra}")
    else:
        failed.append(label)
        print(f"  [FAIL] {label} {extra}")


def _open(opener, method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=20) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return exc.code, exc.read(), dict(exc.headers)


def http(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    """已登录会话的请求。"""
    return _open(OPENER, method, path, data, headers)


def http_anon(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    """匿名请求（不带会话 Cookie）。"""
    return _open(ANON, method, path, data, headers)


def cookie_header() -> str:
    """把会话 Cookie 拼成 WebSocket 握手要用的 Cookie 头。"""
    return "; ".join(f"{c.name}={c.value}" for c in JAR)


def ws_connect(url: str):
    """建立 WebSocket 连接；需要时在握手头里带上会话 Cookie。

    返回 websockets 的 connect 对象（可直接用于 ``async with``）。
    """
    import websockets

    headers = {"Cookie": cookie_header()} if cookie_header() else None
    if not headers:
        return websockets.connect(url)
    try:
        # websockets >= 14 用 additional_headers，旧版用 extra_headers
        return websockets.connect(url, additional_headers=headers)
    except TypeError:
        return websockets.connect(url, extra_headers=headers)


def login() -> bool:
    """登记昵称（本站不做核验，服务端只记录名字）。

    必须走带 Cookie 箱的 OPENER，否则服务端下发的身份 Cookie 会被丢掉。
    """
    payload = json.dumps({"username": NAME}).encode()
    status, body, _ = http("POST", "/api/login", payload,
                           {"Content-Type": "application/json"})
    if status != 200:
        print(f"  登录失败（HTTP {status}）：{body[:200]!r}")
        return False
    return True


def test_auth_gate() -> None:
    """身份门禁：没登记昵称时拿不到数据，登记之后全站通行。"""
    print("\n[0] 身份门禁")

    status, body, _ = http_anon("GET", "/api/posts")
    check("未登记访问 /api/posts 被拒绝", status == 401, f"HTTP {status}")

    status, _, _ = http_anon("GET", "/login.html")
    check("登记页可直接打开", status == 200, f"HTTP {status}")

    status, body, _ = http_anon("POST", "/api/login",
                                json.dumps({"username": "   "}).encode(),
                                {"Content-Type": "application/json"})
    check("空昵称被拒绝", status == 422, f"HTTP {status}")

    check(f"登记昵称「{NAME}」", login())

    status, body, _ = http("GET", "/api/session")
    info = json.loads(body)
    check("会话返回当前身份",
          status == 200 and (info.get("user") or {}).get("name") == NAME,
          str(info.get("user")))

    status, _, _ = http("GET", "/api/posts")
    check("登记后可访问接口", status == 200, f"HTTP {status}")

    status, _, _ = http("GET", "/api/health")
    check("健康检查保持公开", status == 200, f"HTTP {status}")


def test_http() -> None:
    print("\n[1] HTTP 接口")
    status, body, _ = http("GET", "/api/health")
    health = json.loads(body)
    check("GET /api/health", status == 200 and health["status"] == "ok",
          f"engine={health['cpp_extension']}")

    payload = json.dumps({"title": "冒烟测试文章", "content": "第一行\n第二行"}).encode()
    status, body, _ = http("POST", "/api/posts", payload, {"Content-Type": "application/json"})
    post = json.loads(body)
    check("POST /api/posts", status == 201 and post["id"] > 0, f"id={post.get('id')}")

    status, body, _ = http("GET", "/api/posts")
    check("GET /api/posts", status == 200 and any(p["id"] == post["id"] for p in json.loads(body)))

    status, body, _ = http("GET", f"/api/posts/{post['id']}")
    check("GET /api/posts/{id}", status == 200 and json.loads(body)["content"].endswith("第二行"))

    # 文件上传（multipart 手写构造，避免额外依赖）
    blob = bytes((i * 17 + 3) % 256 for i in range(120_000))
    boundary = "----smoke" + hashlib.md5(blob[:32]).hexdigest()
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="smoke.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()
    status, body, _ = http("POST", "/api/upload", parts,
                           {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    upload = json.loads(body)
    check("POST /api/upload", status == 200 and upload["file"]["size"] == len(blob),
          f"engine={upload.get('engine')}")
    check("SHA-256 与本地一致",
          upload["file"]["sha256"] == hashlib.sha256(blob).hexdigest())

    status, body, _ = http("GET", upload["file"]["download_url"])
    check("GET /api/download", status == 200 and body == blob)

    status, body, _ = http("GET", "/api/files")
    check("GET /api/files", status == 200 and len(json.loads(body)) >= 1)

    status, _, _ = http("GET", "/api/download/..%2F..%2Fapp.db")
    check("下载路径穿越被拒绝", status == 404)

    for page in ("/index.html", "/blog.html", "/files.html", "/chat.html", "/canvas.html"):
        status, body, _ = http("GET", page)
        check(f"静态页面 {page}", status == 200 and b"<html" in body.lower())

    status, _, _ = http("GET", "/")
    check("根路径可访问", status in (200, 307))

    # 清理：删掉本次冒烟产生的文章与文件
    http("DELETE", f"/api/posts/{post['id']}")
    http("DELETE", f"/api/files/{upload['file']['id']}")


async def test_ws() -> None:
    print("\n[2] WebSocket 实时通道")
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("  [SKIP] 未安装 websockets 库")
        return

    room = "smoke-room"
    async with ws_connect(f"{WS}/ws?room={room}") as a:
        welcome = json.loads(await a.recv())
        check("welcome 消息", welcome["type"] == "welcome", f"users={len(welcome['users'])}")

        async with ws_connect(f"{WS}/ws?room={room}") as b:
            json.loads(await b.recv())
            join = json.loads(await a.recv())
            check("加入事件广播", join["type"] == "join" and join["user"] == NAME)

            await b.send(json.dumps({"type": "chat", "text": "你好", "room": room}))
            chat_a = json.loads(await a.recv())
            chat_b = json.loads(await b.recv())
            check("聊天同房间广播", chat_a["text"] == "你好" and chat_b["text"] == "你好")

            await a.send(json.dumps({
                "type": "draw", "from": {"x": 0.1, "y": 0.1}, "to": {"x": 0.9, "y": 0.9},
                "color": "#ff0000", "width": 4, "room": room,
            }))
            stroke = json.loads(await b.recv())
            check("绘制动作同步", stroke["type"] == "draw" and stroke["to"]["x"] == 0.9)

        # b 已断开，a 应收到 leave
        leave = json.loads(await a.recv())
        check("断开清理", leave["type"] == "leave" and leave["user"] == NAME)

    async with ws_connect(f"{WS}/ws?room={room}") as c:
        welcome = json.loads(await c.recv())
        check("后加入者收到画布历史", len(welcome["canvas_history"]) >= 1,
              f"history={len(welcome['canvas_history'])}")

    # 房间隔离
    async with ws_connect(f"{WS}/ws?room=smoke-other") as d:
        json.loads(await d.recv())
        async with ws_connect(f"{WS}/ws?room=smoke-other") as e:
            json.loads(await e.recv())
            join_d = json.loads(await d.recv())
            check("不同房间互不干扰", join_d["type"] == "join" and join_d["room"] == "smoke-other")

    status, body, _ = http("GET", "/api/rooms")
    check("GET /api/rooms", status == 200)


def main() -> int:
    print(f"目标服务: {BASE}")
    try:
        http_anon("GET", "/api/health")
    except Exception as exc:  # noqa: BLE001
        print(f"无法连接服务：{exc}")
        return 2

    test_auth_gate()
    test_http()
    asyncio.run(test_ws())

    print(f"\n通过 {passed} 项，失败 {len(failed)} 项")
    if failed:
        for name in failed:
            print(f"  - {name}")
        return 1
    print("端到端验证全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
