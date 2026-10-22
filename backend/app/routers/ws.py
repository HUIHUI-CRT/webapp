"""WebSocket 端点：聊天与画布共用一条连接，用消息 type 区分。

与 HTTP 的关系（重要）：
    WebSocket 不是另一套网络协议栈，它**建立在 HTTP 之上**。客户端先发一个
    带 ``Upgrade: websocket`` 的普通 HTTP GET 请求：

        GET /ws?user=甲&room=lobby HTTP/1.1
        Host: 127.0.0.1:8000
        Upgrade: websocket
        Connection: Upgrade
        Sec-WebSocket-Key: <随机串>
        Sec-WebSocket-Version: 13

    服务端（Uvicorn + 本文件）回 101 Switching Protocols 之后，同一条 TCP
    连接就不再走「请求-响应」模型，转而收发 WebSocket 帧。所以：

    * 端口是同一个（8000），不需要额外开端口、不需要额外防火墙规则；
    * 查询串 ``?user=&room=`` 是**握手时**的 HTTP 参数，用 FastAPI 的
      ``Query(...)`` 读取，连接建立后无法再改（房间以连接为准）；
    * 之后每条消息都是 JSON 帧，``room`` 字段仅用于跨房间转发与兼容，
      真正决定广播范围的是握手时确定的 ``client.room``。

客户端 -> 服务端：
    {"type": "chat",  "text": "...", "user": "...", "room": "..."}
    {"type": "draw",  "from": {"x":0,"y":0}, "to": {"x":1,"y":1},
                      "color": "#000", "width": 3, "room": "..."}
    {"type": "clear", "room": "..."}
    {"type": "ping"}
    {"type": "join"|"leave", "user": "...", "room": "..."}

服务端 -> 客户端：
    {"type": "welcome", ...}   连接建立，携带房间历史与在线用户
    {"type": "chat", ...}      广播的聊天消息，带服务端时间戳
    {"type": "draw", ...}      广播的绘制动作（不回发给发起者）
    {"type": "clear", ...}     清空画布
    {"type": "join"|"leave", ...} 成员变动
    {"type": "presence", ...}  当前在线名单
    {"type": "error", ...}     载荷不合法
"""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..auth import normalize_name
from ..services import Client, hub

# 这个 router 不带 prefix：完整路径就是下面的 "/ws"
router = APIRouter(tags=["realtime"])

MAX_TEXT = 4000   # 单条聊天文本上限，防止超大帧
MAX_ROOM = 64     # 房间名长度上限


def _clean_room(value: Any, fallback: str = "lobby") -> str:
    """规范化房间名：去空白、限长、空值回落到默认房间。"""
    text = str(value or "").strip()[:MAX_ROOM]
    return text or fallback


def _num(value: Any, default: float = 0.0) -> float:
    """宽松地把任意输入转成浮点数，失败则用默认值（前端可能传字符串）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _point(raw: Any) -> Dict[str, float]:
    """把 {"x":..,"y":..} 规范化成坐标字典，缺字段或类型不对一律补 0。"""
    if not isinstance(raw, dict):
        return {"x": 0.0, "y": 0.0}
    return {"x": _num(raw.get("x")), "y": _num(raw.get("y"))}


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    room: str = Query("lobby", description="房间名"),
) -> None:
    """WS /ws?room=<房间> —— 聊天与画布的公共实时通道。

    昵称不再由前端传入：它来自身份 Cookie，由 auth.IdentityMiddleware 解析后
    挂在 ``ws.state.user`` 上。这样同一个人在所有页面、所有房间里名字一致，
    也无法通过改 URL 参数冒充别人。

    生命周期：
        握手成功 -> 注册到 hub 的房间 -> 回发 welcome（含历史）-> 广播 join
        -> 循环处理消息 -> 断开时注销并广播 leave
    """
    await ws.accept()  # 完成 101 Switching Protocols，HTTP 到此结束
    # 中间件已经把昵称放进 scope["state"]；取不到说明走了非预期路径，兜底为「访客」
    name = normalize_name(getattr(ws.state, "user", "")) or "访客"
    client = Client(ws=ws, user=name, room=_clean_room(room), color=hub.next_color())
    await hub.register(client)

    # 入场：先把房间历史发给新连接（补齐上下文），再通知其他成员
    await ws.send_json(
        {
            "type": "welcome",
            "you": client.public(),              # 含服务端分配的 id 与颜色
            "users": hub.users(client.room),     # 当前在线名单
            "chat_history": hub.chat_history(client.room),
            "canvas_history": hub.canvas_history(client.room),
            "server_time": time.time(),
        }
    )
    # exclude=client：自己不需要收到自己的加入事件
    await hub.broadcast(
        client.room,
        {
            "type": "join",
            "user": client.user,
            "room": client.room,
            "client": client.public(),
            "users": hub.users(client.room),
            "ts": time.time(),
        },
        exclude=client,
    )

    try:
        # ---------------------------------------------------- 消息循环
        while True:
            try:
                message = await ws.receive_json()
            except WebSocketDisconnect:
                raise  # 客户端正常关闭，交给外层 finally
            except Exception:
                # 收到非 JSON 帧：回一条错误，连接继续可用
                await ws.send_json({"type": "error", "detail": "消息必须是合法 JSON"})
                continue

            if not isinstance(message, dict):
                await ws.send_json({"type": "error", "detail": "消息必须是 JSON 对象"})
                continue

            kind = str(message.get("type", "")).lower()
            # room 以连接为准：消息里带 room 时用它做转发目标，否则用连接的房间
            target_room = _clean_room(message.get("room"), client.room)

            # 心跳：前端每 25 秒发一次，用于探活与保持连接
            if kind == "ping":
                await ws.send_json({"type": "pong", "ts": time.time()})
                continue

            # 聊天：存历史后广播给房间内所有人（含发送者，便于确认送达）
            if kind == "chat":
                text = str(message.get("text", ""))[:MAX_TEXT].strip()
                if not text:
                    continue  # 空消息直接忽略
                payload = {
                    "type": "chat",
                    "user": client.user,   # 身份取自会话，忽略前端传参
                    "room": target_room,
                    "text": text,
                    "client_id": client.id,   # 前端据此判断「这条是不是我发的」
                    "color": client.color,
                    "ts": time.time(),
                }
                hub.add_chat(target_room, payload)
                await hub.broadcast(target_room, payload)
                continue

            # 绘制：一条消息就是一段线，只存不改，天然免冲突
            if kind == "draw":
                stroke = {
                    "type": "draw",
                    "from": _point(message.get("from")),
                    "to": _point(message.get("to")),
                    "color": str(message.get("color") or client.color)[:16],
                    "width": max(1.0, min(40.0, _num(message.get("width"), 3.0))),
                    "room": target_room,
                    "user": client.user,
                    "client_id": client.id,
                    "ts": time.time(),
                }
                hub.add_stroke(target_room, stroke)
                # 发起者已本地绘制，不回发自己，避免重复画一遍
                await hub.broadcast(target_room, stroke, exclude=client)
                continue

            # 清空画布：清掉内存历史并通知其他人重绘
            if kind == "clear":
                hub.clear_canvas(target_room)
                await hub.broadcast(
                    target_room,
                    {
                        "type": "clear",
                        "room": target_room,
                        "user": client.user,
                        "client_id": client.id,
                        "ts": time.time(),
                    },
                    exclude=client,
                )
                continue

            # 显式 join/leave（当前前端未使用，保留给自定义客户端）
            if kind in ("join", "leave"):
                await hub.broadcast(
                    target_room,
                    {
                        "type": kind,
                        "user": client.user,   # 身份取自会话，忽略前端传参
                        "room": target_room,
                        "users": hub.users(target_room),
                        "ts": time.time(),
                    },
                    exclude=client,
                )
                continue

            # 未知类型：告知客户端但不中断连接
            await ws.send_json({"type": "error", "detail": f"未知消息类型: {kind or '(空)'}"})

    except WebSocketDisconnect:
        pass  # 正常断开路径，无需额外处理
    finally:
        # 无论怎么退出都要清理，否则房间会残留死连接（对应风险表的「连接管理」）
        removed = await hub.unregister(client)
        if removed:
            await hub.broadcast(
                client.room,
                {
                    "type": "leave",
                    "user": client.user,
                    "room": client.room,
                    "client": client.public(),
                    "users": hub.users(client.room),
                    "ts": time.time(),
                },
            )
