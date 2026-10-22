"""身份门禁验收：登记昵称、Cookie 校验、拦截面、WebSocket 身份。

本站不做身份核验，因此这里测的不是「密码对不对」，而是：
    * 没登记昵称时能不能被拦住；
    * 登记之后身份是否贯穿 HTTP 与 WebSocket；
    * 昵称规范化与令牌防篡改是否正常。
"""

from __future__ import annotations

import time

import pytest

from backend.app import auth


@pytest.fixture()
def anon(client):
    """干净的客户端：清掉会话 Cookie，模拟第一次访问。"""
    client.cookies.clear()
    yield client
    # 用完恢复身份，避免影响后续用例
    client.cookies.clear()
    client.post("/api/login", json={"username": "测试用户"})


# ------------------------------------------------------------------ 昵称与令牌
def test_normalize_name_collapses_space_and_trims():
    assert auth.normalize_name("  小林  ") == "小林"
    assert auth.normalize_name("阿   青") == "阿 青"
    assert auth.normalize_name("x" * 40) == "x" * auth.NAME_MAX
    assert auth.normalize_name("") == ""


def test_token_roundtrip_keeps_name():
    token = auth.make_token("小林")
    assert auth.verify_token(token) == "小林"


def test_token_supports_chinese_and_symbols():
    token = auth.make_token("阿 青🎨")
    assert auth.verify_token(token) == "阿 青🎨"


def test_expired_token_rejected():
    token = auth.make_token("小林", now=time.time() - auth.SESSION_DAYS * 86400 - 10)
    assert auth.verify_token(token) is None


def test_tampered_token_rejected():
    token = auth.make_token("小林")
    encoded, expires, signature = token.split(".")
    forged_name = auth._b64("管理员")
    assert auth.verify_token(f"{forged_name}.{expires}.{signature}") is None
    assert auth.verify_token(f"{encoded}.{int(expires) + 999999}.{signature}") is None
    assert auth.verify_token(f"{encoded}.{expires}.{'0' * len(signature)}") is None
    assert auth.verify_token("garbage") is None
    assert auth.verify_token(None) is None


# ------------------------------------------------------------------ 拦截面
def test_api_requires_identity(anon):
    res = anon.get("/api/posts")
    assert res.status_code == 401
    assert res.json()["login_url"] == "/login.html"


def test_page_redirects_to_login(anon):
    res = anon.get("/index.html", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].startswith("/login.html?next=")


def test_public_paths(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/login.html").status_code == 200
    assert anon.get("/api/session").status_code == 200


def test_session_reports_no_identity(anon):
    info = anon.get("/api/session").json()
    assert info["authenticated"] is False
    assert info["user"] is None


def test_empty_name_rejected(anon):
    assert anon.post("/api/login", json={"username": "   "}).status_code == 422
    assert anon.post("/api/login", json={}).status_code == 422


# ------------------------------------------------------------------ 登记
def test_login_sets_identity_and_unlocks(anon):
    res = anon.post("/api/login", json={"username": "小林"})
    assert res.status_code == 200
    assert res.json()["user"]["name"] == "小林"
    assert auth.COOKIE_NAME in anon.cookies

    assert anon.get("/api/posts").status_code == 200
    assert anon.get("/index.html").status_code == 200
    session = anon.get("/api/session").json()
    assert session["authenticated"] is True
    assert session["user"]["name"] == "小林"


def test_identity_is_used_by_business_data(anon):
    anon.post("/api/login", json={"username": "阿青"})

    post = anon.post("/api/posts", json={"title": "身份测试", "content": "正文"}).json()
    assert post["author"] == "阿青"

    task = anon.post("/api/tasks", json={"title": "身份任务"}).json()
    assert task["created_by"] == "阿青"

    poll = anon.post("/api/polls", json={"title": "身份投票", "options": ["A", "B"]}).json()
    assert poll["created_by"] == "阿青"


def test_logout_clears_identity(anon):
    anon.post("/api/login", json={"username": "小林"})
    assert anon.get("/api/posts").status_code == 200
    anon.post("/api/logout")
    assert anon.get("/api/posts").status_code == 401


def test_rename_switches_identity(anon):
    anon.post("/api/login", json={"username": "小林"})
    anon.post("/api/login", json={"username": "阿青"})
    assert anon.get("/api/session").json()["user"]["name"] == "阿青"


# ------------------------------------------------------------------ WebSocket
def test_websocket_requires_identity(anon):
    with pytest.raises(Exception):
        with anon.websocket_connect("/ws?room=guarded") as ws:
            ws.receive_json()


def test_websocket_uses_cookie_identity_ignoring_query(anon):
    anon.post("/api/login", json={"username": "阿青"})
    # 故意在查询串里塞一个别的名字，服务端应当忽略它
    with anon.websocket_connect("/ws?room=identity-test&user=冒充者") as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        assert welcome["you"]["user"] == "阿青"
