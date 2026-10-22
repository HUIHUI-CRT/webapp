"""SQLite 访问层。

设计取舍：
    * 每个请求使用独立连接（SQLite 官方推荐的线程模型），配合 WAL 与
      busy_timeout 降低并发写入冲突。
    * 连接以 ``sqlite3.Row`` 作为 row_factory，路由层直接得到字典样式的行。
    * 建表语句幂等，服务每次启动都会调用 :func:`init_db`。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    author      TEXT    NOT NULL DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT    NOT NULL UNIQUE,
    original_name TEXT    NOT NULL,
    size          INTEGER NOT NULL,
    sha256        TEXT,
    uploader      TEXT    NOT NULL DEFAULT '',
    uploaded_at   TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'doing', 'done')),
    priority    TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
    assignee    TEXT NOT NULL DEFAULT '',
    due_date    TEXT,
    created_by  TEXT NOT NULL DEFAULT '小组成员',
    created_at  TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    created_by  TEXT NOT NULL DEFAULT '小组成员',
    ends_at     TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS poll_options (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id     INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    label       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS poll_votes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id     INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    option_id   INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
    voter       TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (poll_id, voter)
);

CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id   INTEGER,
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_posts_created ON posts (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_files_sha256  ON files (sha256);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_polls_created ON polls (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_poll_votes_poll ON poll_votes (poll_id, option_id);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity (created_at DESC, id DESC);
"""


def connect() -> sqlite3.Connection:
    """建立一个配置好的新连接，调用方负责关闭。

    ``check_same_thread=False`` 的原因：FastAPI 的同步依赖发生器在线程池中
    执行，而异步路由（如文件上传）在事件循环线程中执行，两者拿到的是同一条
    连接。由于每个请求独占一条连接、且使用是先后串行的，关闭线程校验不会
    引入并发访问；真正需要防范的是「一条连接被多线程同时读写」，这里不存在。
    """
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """上下文管理器：正常提交，异常回滚，最后关闭。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# 轻量迁移：给已存在的旧库补上后来新增的列。
# 只做「加列」这种向后兼容的改动，不改类型、不删列，旧数据自动取默认值。
_ADDED_COLUMNS = {
    "posts": {"author": "TEXT NOT NULL DEFAULT ''"},
    "files": {"uploader": "TEXT NOT NULL DEFAULT ''"},
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    """创建目录与全部表结构（幂等），并补齐旧库缺少的列。"""
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def db_dependency() -> Iterator[sqlite3.Connection]:
    """FastAPI 依赖：为每个请求提供一个连接。

    路由里写 ``conn: sqlite3.Connection = Depends(db_dependency)`` 即可拿到
    连接；请求处理完成后（无论成功还是抛 HTTPException）都会走这里的收尾
    逻辑，自动提交/回滚并关闭连接，因此业务代码不需要写 try/finally。

    请求级连接也是计划书「SQLite 并发写入冲突」的应对措施：写操作彼此隔离，
    配合 WAL 与 busy_timeout，多个请求同时写入不会互相阻塞失败。
    """
    with get_conn() as conn:
        yield conn
