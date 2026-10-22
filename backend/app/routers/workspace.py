"""小组协作 API：任务、投票、活动记录、统计与全站搜索。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user
from ..db import db_dependency
from ..schemas import PollCreate, TaskCreate, TaskUpdate, VoteCreate
from ..services.activity import log_activity
from ..services import hub

router = APIRouter(prefix="/api", tags=["workspace"])


def _poll(conn: sqlite3.Connection, row: sqlite3.Row, voter: str = "") -> Dict[str, Any]:
    options = conn.execute(
        "SELECT o.id, o.label, COUNT(v.id) AS votes FROM poll_options o "
        "LEFT JOIN poll_votes v ON v.option_id = o.id WHERE o.poll_id = ? "
        "GROUP BY o.id ORDER BY o.id", (row["id"],),
    ).fetchall()
    mine = conn.execute(
        "SELECT option_id FROM poll_votes WHERE poll_id = ? AND voter = ?",
        (row["id"], voter.strip()[:64]),
    ).fetchone() if voter else None
    return {**dict(row), "options": [dict(option) for option in options],
            "total_votes": sum(option["votes"] for option in options),
            "my_option_id": mine["option_id"] if mine else None}


@router.get("/tasks", summary="获取任务列表")
def list_tasks(status: Optional[str] = Query(None, pattern="^(todo|doing|done)$"),
               conn: sqlite3.Connection = Depends(db_dependency)) -> List[Dict[str, Any]]:
    order = ("CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
             "COALESCE(due_date, '9999-12-31'), updated_at DESC, id DESC")
    if status:
        rows = conn.execute(f"SELECT * FROM tasks WHERE status = ? ORDER BY {order}", (status,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY CASE status WHEN 'todo' THEN 0 WHEN 'doing' THEN 1 ELSE 2 END, " + order
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/tasks", status_code=201, summary="创建任务")
def create_task(payload: TaskCreate, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(db_dependency)) -> Dict[str, Any]:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="任务标题不能为空")
    due_date = payload.due_date.strip() if payload.due_date else None
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="截止日期必须使用 YYYY-MM-DD 格式") from exc
    cur = conn.execute(
        "INSERT INTO tasks (title, description, status, priority, assignee, due_date, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, payload.description.strip(), payload.status, payload.priority,
         payload.assignee.strip(), due_date, user),
    )
    task_id = int(cur.lastrowid)
    log_activity(conn, "创建了任务", user, "task", task_id, title)
    return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


@router.patch("/tasks/{task_id}", summary="更新任务")
def update_task(task_id: int, payload: TaskUpdate, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(db_dependency)) -> Dict[str, Any]:
    current = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if current is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    updates = payload.model_dump(exclude_unset=True)
    updates = {key: value for key, value in updates.items() if value is not None or key == "due_date"}
    if not updates:
        return dict(current)
    if "title" in updates and not (updates["title"] or "").strip():
        raise HTTPException(status_code=422, detail="任务标题不能为空")
    if "due_date" in updates and updates["due_date"]:
        try:
            date.fromisoformat(updates["due_date"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="截止日期必须使用 YYYY-MM-DD 格式") from exc
    for key in ("title", "description", "assignee"):
        if key in updates:
            updates[key] = updates[key].strip()
    assignments = [f"{key} = ?" for key in updates]
    values = list(updates.values()) + [task_id]
    assignments.append("updated_at = datetime('now', 'localtime')")
    conn.execute(f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?", values)
    log_activity(conn, "更新了任务", user, "task", task_id, updates.get("title") or current["title"])
    return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


@router.delete("/tasks/{task_id}", summary="删除任务")
def delete_task(task_id: int, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(db_dependency)) -> Dict[str, Any]:
    row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    log_activity(conn, "删除了任务", user, "task", task_id, row["title"])
    return {"ok": True}


@router.get("/polls", summary="获取投票及实时结果")
def list_polls(user: str = Depends(current_user),
               conn: sqlite3.Connection = Depends(db_dependency)) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM polls ORDER BY id DESC LIMIT 100").fetchall()
    return [_poll(conn, row, user) for row in rows]


@router.post("/polls", status_code=201, summary="创建投票")
def create_poll(payload: PollCreate, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(db_dependency)) -> Dict[str, Any]:
    title = payload.title.strip()
    options = list(dict.fromkeys(option.strip() for option in payload.options if option.strip()))
    if not title:
        raise HTTPException(status_code=422, detail="投票标题不能为空")
    if len(options) < 2 or len(options) > 8:
        raise HTTPException(status_code=422, detail="请提供 2 至 8 个不重复的选项")
    ends_at = None
    if payload.ends_at:
        try:
            ends_at = datetime.fromisoformat(payload.ends_at).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="截止时间格式无效") from exc
    actor = user
    cur = conn.execute("INSERT INTO polls (title, created_by, ends_at) VALUES (?, ?, ?)",
                       (title, actor, ends_at))
    poll_id = int(cur.lastrowid)
    conn.executemany("INSERT INTO poll_options (poll_id, label) VALUES (?, ?)",
                     [(poll_id, option[:120]) for option in options])
    log_activity(conn, "发起了投票", actor, "poll", poll_id, title)
    row = conn.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
    return _poll(conn, row, actor)


@router.post("/polls/{poll_id}/vote", summary="提交或更新投票")
def cast_vote(poll_id: int, payload: VoteCreate, user: str = Depends(current_user),
              conn: sqlite3.Connection = Depends(db_dependency)) -> Dict[str, Any]:
    poll = conn.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
    if poll is None:
        raise HTTPException(status_code=404, detail="投票不存在")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if poll["ends_at"] and poll["ends_at"] < now:
        raise HTTPException(status_code=409, detail="投票已截止")
    option = conn.execute("SELECT id FROM poll_options WHERE id = ? AND poll_id = ?",
                          (payload.option_id, poll_id)).fetchone()
    if option is None:
        raise HTTPException(status_code=422, detail="该选项不属于此投票")
    voter = user  # 投票人来自已登记的身份，不再由前端传入
    conn.execute(
        "INSERT INTO poll_votes (poll_id, option_id, voter) VALUES (?, ?, ?) "
        "ON CONFLICT(poll_id, voter) DO UPDATE SET option_id = excluded.option_id, "
        "created_at = datetime('now', 'localtime')", (poll_id, payload.option_id, voter),
    )
    log_activity(conn, "参与了投票", voter, "poll", poll_id, poll["title"])
    return _poll(conn, poll, voter)


@router.get("/activity", summary="获取最近的团队活动")
def list_activity(limit: int = Query(30, ge=1, le=100),
                  conn: sqlite3.Connection = Depends(db_dependency)) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, action, actor, target_type, target_id, detail, created_at "
        "FROM activity ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


@router.get("/stats", summary="获取小组协作统计")
def workspace_stats(conn: sqlite3.Connection = Depends(db_dependency)) -> Dict[str, Any]:
    return {
        "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
        "files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "file_bytes": conn.execute("SELECT COALESCE(SUM(size), 0) FROM files").fetchone()[0],
        "tasks": {row["status"]: row["n"] for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()},
        "polls": conn.execute("SELECT COUNT(*) FROM polls").fetchone()[0],
        "active_polls": conn.execute(
            "SELECT COUNT(*) FROM polls WHERE ends_at IS NULL OR ends_at >= datetime('now', 'localtime')"
        ).fetchone()[0],
        "activity": conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0],
        "realtime": hub.stats(),
    }


@router.get("/search", summary="搜索文章、文件、任务和近期聊天")
def search_all(q: str = Query(..., min_length=1, max_length=100),
               conn: sqlite3.Connection = Depends(db_dependency)) -> Dict[str, Any]:
    query = q.strip()
    if not query:
        return {"query": "", "results": []}
    pattern = f"%{query}%"
    results: List[Dict[str, Any]] = []
    for row in conn.execute(
        "SELECT id, title, content, created_at FROM posts WHERE title LIKE ? OR content LIKE ? "
        "ORDER BY id DESC LIMIT 20", (pattern, pattern),
    ).fetchall():
        content = " ".join(row["content"].split())
        position = content.casefold().find(query.casefold())
        start = max(0, position - 50) if position >= 0 else 0
        results.append({"type": "post", "title": row["title"], "snippet": content[start:start + 180],
                        "created_at": row["created_at"], "url": f"/blog.html?post={row['id']}"})
    for row in conn.execute(
        "SELECT filename, original_name, size, uploaded_at FROM files WHERE original_name LIKE ? "
        "ORDER BY id DESC LIMIT 20", (pattern,),
    ).fetchall():
        results.append({"type": "file", "title": row["original_name"], "snippet": f"文件 · {row['size']} 字节",
                        "created_at": row["uploaded_at"], "url": f"/api/download/{quote(row['filename'])}"})
    for row in conn.execute(
        "SELECT title, description, status, priority, updated_at FROM tasks "
        "WHERE title LIKE ? OR description LIKE ? OR assignee LIKE ? ORDER BY id DESC LIMIT 20",
        (pattern, pattern, pattern),
    ).fetchall():
        results.append({"type": "task", "title": row["title"],
                        "snippet": f"{row['status']} · {row['priority']} · {row['description'][:140]}",
                        "created_at": row["updated_at"], "url": "/workspace.html#tasks"})
    for message in hub.search_chat(query, limit=20):
        results.append({"type": "chat", "title": f"{message['user']} · #{message['room']}",
                        "snippet": message["text"][:180], "created_at": message.get("ts"),
                        "url": f"/chat.html?room={quote(message['room'])}"})
    results.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"query": query, "results": results[:50]}
