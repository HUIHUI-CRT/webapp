"""持久化可见的团队操作记录。"""

from __future__ import annotations

import sqlite3
from typing import Optional


def log_activity(conn: sqlite3.Connection, action: str, actor: str = "小组成员",
                 target_type: str = "system", target_id: Optional[int] = None,
                 detail: str = "") -> None:
    conn.execute(
        "INSERT INTO activity (action, actor, target_type, target_id, detail) VALUES (?, ?, ?, ?, ?)",
        (action[:40], (actor.strip() or "小组成员")[:64], target_type[:24], target_id, detail[:240]),
    )
