"""博客模块：文章的创建、列表与详情。

HTTP 契约一览（详细说明与行号见 docs/接口清单.md）：

    GET    /api/posts        列表：只返回标题 + 摘要 + 时间，正文不参与传输
    GET    /api/posts/{id}   详情：返回完整正文，不存在返回 404
    POST   /api/posts        创建：请求体 JSON {"title","content"}，成功 201
    DELETE /api/posts/{id}   删除：成功 200，不存在 404

数据流（对应计划书 7.1）：前端表单 -> POST /api/posts -> 写入 SQLite ->
返回文章 ID -> 前端刷新列表并打开详情。

本模块所有处理函数都是同步 ``def``：FastAPI 会把它们放到线程池执行，
因此这里可以直接使用阻塞的 sqlite3 调用，不会堵住事件循环。
"""

from __future__ import annotations

import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user
from ..db import db_dependency
from ..schemas import DeleteResult, Post, PostCreate, PostSummary
from ..services.activity import log_activity

# prefix="/api" 让下面所有路径都带上 /api 前缀；tags 用于 /docs 分组。
router = APIRouter(prefix="/api", tags=["blog"])

EXCERPT_LEN = 120


def _excerpt(content: str) -> str:
    """把正文压成单行摘要：列表接口只传摘要，减少响应体积。"""
    flat = " ".join(content.split())
    return flat if len(flat) <= EXCERPT_LEN else flat[:EXCERPT_LEN] + "…"


# ---------------------------------------------------------------- 列表
@router.get("/posts", response_model=List[PostSummary], summary="获取文章列表")
def list_posts(
    limit: int = Query(50, ge=1, le=200, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    # Depends 注入的是「每个请求一条」的 SQLite 连接，请求结束自动提交并关闭
    conn: sqlite3.Connection = Depends(db_dependency),
) -> List[PostSummary]:
    """GET /api/posts —— 按创建时间倒序返回文章列表（响应中不含正文）。"""
    rows = conn.execute(
        "SELECT id, title, content, author, created_at FROM posts "
        "ORDER BY datetime(created_at) DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        PostSummary(
            id=row["id"],
            title=row["title"],
            author=row["author"],
            created_at=row["created_at"],
            excerpt=_excerpt(row["content"]),  # 正文在这里被压缩成摘要
        )
        for row in rows
    ]


# ---------------------------------------------------------------- 详情
@router.get("/posts/{post_id}", response_model=Post, summary="获取单篇文章")
def get_post(post_id: int, conn: sqlite3.Connection = Depends(db_dependency)) -> Post:
    """GET /api/posts/{id} —— 返回完整正文；ID 不存在时抛 404。"""
    row = conn.execute(
        "SELECT id, title, content, author, created_at FROM posts WHERE id = ?", (post_id,)
    ).fetchone()
    if row is None:
        # HTTPException 由 FastAPI 转成 {"detail": "..."} 的 JSON 响应
        raise HTTPException(status_code=404, detail=f"文章 {post_id} 不存在")
    return Post(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        content=row["content"],
        created_at=row["created_at"],
        excerpt=_excerpt(row["content"]),
    )


# ---------------------------------------------------------------- 创建
@router.post("/posts", response_model=Post, status_code=201, summary="创建文章")
def create_post(payload: PostCreate, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(db_dependency)) -> Post:
    """POST /api/posts —— 请求体由 PostCreate 校验，通过后插入并回读完整记录。

    作者取自登记的身份（``user``），请求体里不再需要传「我是谁」。
    ``status_code=201`` 表示「已创建」；请求体缺字段或为空会由 Pydantic
    自动返回 422，不会进入函数体。
    """
    cur = conn.execute(
        "INSERT INTO posts (title, content, author) VALUES (?, ?, ?)",
        (payload.title.strip(), payload.content, user),
    )
    post_id = int(cur.lastrowid)
    log_activity(conn, "发布了文章", user, "post", post_id, payload.title.strip())
    # 回读一次，让 created_at 用数据库默认值生成的时间（而不是 Python 侧猜的时间）
    row = conn.execute(
        "SELECT id, title, content, author, created_at FROM posts WHERE id = ?", (post_id,)
    ).fetchone()
    return Post(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        content=row["content"],
        created_at=row["created_at"],
        excerpt=_excerpt(row["content"]),
    )


# ---------------------------------------------------------------- 删除
@router.delete("/posts/{post_id}", response_model=DeleteResult, summary="删除文章")
def delete_post(post_id: int, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(db_dependency)) -> DeleteResult:
    """DELETE /api/posts/{id} —— 按 ID 删除；rowcount 为 0 说明本来就不存在，返回 404。"""
    row = conn.execute("SELECT title FROM posts WHERE id = ?", (post_id,)).fetchone()
    cur = conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"文章 {post_id} 不存在")
    log_activity(conn, "删除了文章", user, "post", post_id, row["title"])
    return DeleteResult(detail=f"已删除文章 {post_id}")
