"""聊天与画布验收：同房间广播、房间隔离、历史补齐、断开清理。

身份来自 Cookie，所以「两个不同的人」要开两个带不同身份 Cookie 的客户端。
``as_user`` 就是一个这样的帮手：每个实例先登记昵称，再建立 WebSocket。
"""

from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from backend.app.main import app


@contextmanager
def as_user(name: str):
    """一个已登记指定昵称的独立客户端（拥有独立的 Cookie 罐）。"""
    with TestClient(app) as c:
        resp = c.post("/api/login", json={"username": name})
        assert resp.status_code == 200, resp.text
        yield c


def _welcome(ws):
    msg = ws.receive_json()
    assert msg["type"] == "welcome", msg
    return msg


def test_chat_broadcast_within_room():
    with as_user("alice") as alice, as_user("bob") as bob:
        with alice.websocket_connect("/ws?room=chat-a") as ws_a:
            _welcome(ws_a)
            with bob.websocket_connect("/ws?room=chat-a") as ws_b:
                _welcome(ws_b)
                # alice 收到 bob 的加入事件，并看到在线名单
                join = ws_a.receive_json()
                assert join["type"] == "join"
                assert join["user"] == "bob"
                assert {u["user"] for u in join["users"]} == {"alice", "bob"}

                # 即使消息体里写了别的名字，服务端也只认 Cookie 里的身份
                ws_b.send_json({"type": "chat", "text": "你好，世界", "user": "冒充者", "room": "chat-a"})
                got = ws_a.receive_json()
                assert got["type"] == "chat"
                assert got["text"] == "你好，世界"
                assert got["user"] == "bob"
                assert got["ts"] > 0
                assert ws_b.receive_json()["text"] == "你好，世界"


def test_chat_room_isolation():
    with as_user("carol") as carol, as_user("dave") as dave, as_user("erin") as erin:
        with carol.websocket_connect("/ws?room=chat-b") as ws_c:
            _welcome(ws_c)
            with dave.websocket_connect("/ws?room=chat-c") as ws_d:
                _welcome(ws_d)
                # dave 在别的房间发消息，carol 不应收到；随后 carol 收到自己房间新成员的加入事件
                ws_d.send_json({"type": "chat", "text": "不该被看到", "user": "dave", "room": "chat-c"})
                with erin.websocket_connect("/ws?room=chat-b") as ws_e:
                    _welcome(ws_e)
                    nxt = ws_c.receive_json()
                    assert nxt["type"] == "join" and nxt["user"] == "erin", nxt


def test_draw_broadcast_and_sender_exclusion():
    with as_user("frank") as frank, as_user("grace") as grace:
        with frank.websocket_connect("/ws?room=draw-a") as ws_f:
            _welcome(ws_f)
            with grace.websocket_connect("/ws?room=draw-a") as ws_g:
                _welcome(ws_g)
                assert ws_f.receive_json()["type"] == "join"

                ws_f.send_json({
                    "type": "draw",
                    "from": {"x": 0.1, "y": 0.2},
                    "to": {"x": 0.3, "y": 0.4},
                    "color": "#ff0000",
                    "width": 5,
                    "room": "draw-a",
                })
                stroke = ws_g.receive_json()
                assert stroke["type"] == "draw"
                assert stroke["from"] == {"x": 0.1, "y": 0.2}
                assert stroke["to"] == {"x": 0.3, "y": 0.4}
                assert stroke["color"] == "#ff0000"
                assert stroke["width"] == 5
                assert stroke["user"] == "frank"

                # 发起者不应收到自己的绘制动作：grace 发消息后，frank 收到的第一条就是它
                ws_g.send_json({"type": "chat", "text": "收到线条", "user": "grace", "room": "draw-a"})
                assert ws_f.receive_json()["text"] == "收到线条"


def test_canvas_history_replayed_to_late_joiner():
    with as_user("henry") as henry, as_user("ivy") as ivy:
        with henry.websocket_connect("/ws?room=draw-b") as ws_h:
            _welcome(ws_h)
            for index in range(3):
                ws_h.send_json({
                    "type": "draw",
                    "from": {"x": index / 10, "y": 0},
                    "to": {"x": index / 10, "y": 1},
                    "room": "draw-b",
                })
            with ivy.websocket_connect("/ws?room=draw-b") as ws_i:
                welcome = _welcome(ws_i)
                assert len(welcome["canvas_history"]) == 3
                assert welcome["canvas_history"][0]["from"]["x"] == 0
                assert welcome["canvas_history"][0]["user"] == "henry"


def test_clear_canvas():
    with as_user("jack") as jack, as_user("kate") as kate, as_user("liam") as liam:
        with jack.websocket_connect("/ws?room=draw-c") as ws_j:
            _welcome(ws_j)
            with kate.websocket_connect("/ws?room=draw-c") as ws_k:
                _welcome(ws_k)
                assert ws_j.receive_json()["type"] == "join"

                ws_j.send_json({"type": "draw", "from": {"x": 0, "y": 0}, "to": {"x": 1, "y": 1}, "room": "draw-c"})
                assert ws_k.receive_json()["type"] == "draw"

                ws_j.send_json({"type": "clear", "room": "draw-c"})
                assert ws_k.receive_json()["type"] == "clear"

                with liam.websocket_connect("/ws?room=draw-c") as ws_l:
                    assert _welcome(ws_l)["canvas_history"] == []


def test_ping_pong():
    with as_user("mia") as mia:
        with mia.websocket_connect("/ws?room=ping-room") as ws:
            _welcome(ws)
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


def test_bad_payload_reports_error():
    with as_user("nick") as nick:
        with nick.websocket_connect("/ws?room=bad-room") as ws:
            _welcome(ws)
            ws.send_json({"type": "unknown-kind"})
            assert ws.receive_json()["type"] == "error"


def test_disconnect_cleans_up_room_state():
    with as_user("olive") as olive, as_user("pete") as pete:
        with olive.websocket_connect("/ws?room=cleanup") as ws_o:
            _welcome(ws_o)
            with pete.websocket_connect("/ws?room=cleanup") as ws_p:
                _welcome(ws_p)
                assert ws_o.receive_json()["type"] == "join"
            # pete 断开后，olive 应收到 leave，房间人数回落
            leave = ws_o.receive_json()
            assert leave["type"] == "leave" and leave["user"] == "pete"
            assert [u["user"] for u in leave["users"]] == ["olive"]

        stats = olive.get("/api/rooms").json()
        assert "cleanup" not in stats["rooms"]
