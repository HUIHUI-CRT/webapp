"""实时广播中心：聊天与画布共用一个 WebSocket 服务，通过消息 type 区分。

职责：
    * 维护「房间 -> 连接集合」的映射；
    * 提供广播能力，并在发送失败时清理失效连接；
    * 保存每个房间的轻量内存历史（聊天消息、绘制动作），供后加入的
      客户端补齐上下文；
    * 记录在线用户的昵称与颜色。

并发说明：所有结构都在同一个事件循环中被修改；``asyncio.Lock`` 用于保护
「快照 + 修改」这段临界区，实际网络发送在锁外进行，避免慢客户端阻塞广播。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, List, Optional, Set

from fastapi import WebSocket

from .. import config

PALETTE = [
    "#e5484d", "#2b7de9", "#12a594", "#f5a524", "#8e4ec6",
    "#e93d82", "#3e63dd", "#30a46c", "#f76808", "#0d9488",
]


@dataclass(eq=False)
class Client:
    """一条 WebSocket 连接的元数据。eq=False 让对象按身份参与集合运算。"""

    ws: WebSocket
    user: str
    room: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    color: str = PALETTE[0]
    connected_at: float = field(default_factory=time.time)

    def public(self) -> Dict[str, Any]:
        return {"id": self.id, "user": self.user, "room": self.room, "color": self.color}


class Hub:
    def __init__(self) -> None:
        self._rooms: Dict[str, Set[Client]] = {}
        self._chat: Dict[str, Deque[Dict[str, Any]]] = {}
        self._canvas: Dict[str, Deque[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._color_seq = 0

    # ------------------------------------------------------------ 连接管理
    def next_color(self) -> str:
        color = PALETTE[self._color_seq % len(PALETTE)]
        self._color_seq += 1
        return color

    async def register(self, client: Client) -> None:
        async with self._lock:
            self._rooms.setdefault(client.room, set()).add(client)

    async def unregister(self, client: Client) -> bool:
        """移除连接。返回 True 表示该连接此前确实在房间内。"""
        async with self._lock:
            members = self._rooms.get(client.room)
            if not members or client not in members:
                return False
            members.discard(client)
            if not members:
                self._rooms.pop(client.room, None)
            return True

    def users(self, room: str) -> List[Dict[str, Any]]:
        return [c.public() for c in self._rooms.get(room, ())]

    def usernames(self, room: str) -> List[str]:
        return [c.user for c in self._rooms.get(room, ())]

    def rooms(self) -> Dict[str, int]:
        return {room: len(members) for room, members in self._rooms.items()}

    def stats(self) -> Dict[str, Any]:
        return {
            "rooms": self.rooms(),
            "connections": sum(len(m) for m in self._rooms.values()),
        }

    # ------------------------------------------------------------ 历史缓存
    @staticmethod
    def _append(store: Dict[str, Deque[Dict[str, Any]]], room: str, item: Dict[str, Any], limit: int) -> None:
        if limit <= 0:
            return
        bucket = store.get(room)
        if bucket is None:
            bucket = deque(maxlen=limit)
            store[room] = bucket
        bucket.append(item)

    def add_chat(self, room: str, message: Dict[str, Any]) -> None:
        self._append(self._chat, room, message, config.CHAT_HISTORY_LIMIT)

    def chat_history(self, room: str) -> List[Dict[str, Any]]:
        return list(self._chat.get(room, ()))

    def search_chat(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        needle = query.casefold()
        matches = [
            {**message, "room": room}
            for room, messages in self._chat.items()
            for message in messages
            if needle in str(message.get("text", "")).casefold()
        ]
        return sorted(matches, key=lambda message: message.get("ts", 0), reverse=True)[:limit]

    def add_stroke(self, room: str, stroke: Dict[str, Any]) -> None:
        self._append(self._canvas, room, stroke, config.CANVAS_HISTORY_LIMIT)

    def canvas_history(self, room: str) -> List[Dict[str, Any]]:
        return list(self._canvas.get(room, ()))

    def clear_canvas(self, room: str) -> None:
        self._canvas.pop(room, None)

    # ------------------------------------------------------------ 广播
    async def broadcast(
        self,
        room: str,
        payload: Dict[str, Any],
        exclude: Optional[Client] = None,
        only: Optional[Iterable[Client]] = None,
    ) -> int:
        """向房间（或指定子集）广播，返回成功发送的连接数。

        发送失败的连接会被立即摘除，避免死连接长期占用内存。
        """
        targets = list(only) if only is not None else list(self._rooms.get(room, ()))
        if exclude is not None:
            targets = [c for c in targets if c is not exclude]
        if not targets:
            return 0

        dead: List[Client] = []
        sent = 0
        for client in targets:
            try:
                await client.ws.send_json(payload)
                sent += 1
            except Exception:  # 客户端断开、网络异常等
                dead.append(client)

        if dead:
            async with self._lock:
                for client in dead:
                    members = self._rooms.get(client.room)
                    if members:
                        members.discard(client)
                        if not members:
                            self._rooms.pop(client.room, None)
        return sent


hub = Hub()
