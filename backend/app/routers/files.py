"""文件共享模块：上传、下载、列表。

HTTP 契约一览（详细说明与行号见 docs/接口清单.md）：

    GET    /api/files                列表：文件名、大小、时间、SHA-256、下载地址
    POST   /api/upload               上传：multipart/form-data，字段名 file，成功 200
    GET    /api/download/{filename}  下载：按「存储名」取文件，响应头还原原始文件名
    GET    /api/files/{id}           单个文件元数据
    DELETE /api/files/{id}           删除：同时删数据库记录与磁盘文件

关于 multipart/form-data：
    浏览器通过 FormData 提交时，请求体是 multipart 分段格式，Content-Type 形如
    ``multipart/form-data; boundary=----WebKitFormBoundaryXXX``。
    FastAPI 依赖 ``python-multipart`` 解析它，并把 ``File(...)`` 参数解析成
    ``UploadFile`` 对象（大文件会被 Starlette 先落到临时文件，避免占内存）。
    本模块再用 ``await file.read(chunk)`` 分块读出、亲手写入 uploads/。

安全要点（对应计划书风险表）：
    * 原始文件名只做展示与下载头，落盘名一律换成 UUID，杜绝重名覆盖；
    * 下载接口只接受数据库中登记过的存储名，并二次校验解析路径仍在上传目录内；
    * 上传过程累计字节数，超过 APP_MAX_UPLOAD_BYTES 立即中断并删除半成品。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import config
from ..auth import current_user
from ..db import db_dependency
from ..ext import ENGINE, sha256_file
from ..schemas import DeleteResult, FileInfo, UploadResult
from ..services.activity import log_activity

router = APIRouter(prefix="/api", tags=["files"])

# Windows 保留字符 + 路径分隔符，统一替换掉，防止 "../" 之类的路径穿越
_UNSAFE = '<>:"/\\|?*'


def sanitize_name(name: str) -> str:
    """清洗原始文件名：去掉目录成分与危险字符，保留扩展名。

    ``Path(name).name`` 会丢掉 ``../../etc/passwd`` 这样的目录部分，
    因此磁盘上永远不会因为用户提交的文件名而写到 uploads/ 之外。
    """
    base = Path(name or "unnamed").name
    cleaned = "".join("_" if ch in _UNSAFE or ord(ch) < 32 else ch for ch in base).strip(" .")
    return cleaned[:180] or "unnamed"


def _row_to_info(row: sqlite3.Row) -> FileInfo:
    """数据库行 -> 响应模型；下载地址由存储名拼出，前端直接拿来当链接用。"""
    return FileInfo(
        id=row["id"],
        filename=row["filename"],
        original_name=row["original_name"],
        size=row["size"],
        sha256=row["sha256"],
        uploader=row["uploader"],
        uploaded_at=row["uploaded_at"],
        download_url=f"/api/download/{row['filename']}",
    )


# ---------------------------------------------------------------- 列表
@router.get("/files", response_model=List[FileInfo], summary="获取文件列表")
def list_files(conn: sqlite3.Connection = Depends(db_dependency)) -> List[FileInfo]:
    """GET /api/files —— 按上传时间倒序返回全部文件元数据（不含文件内容）。"""
    rows = conn.execute(
        "SELECT id, filename, original_name, size, sha256, uploader, uploaded_at FROM files "
        "ORDER BY datetime(uploaded_at) DESC, id DESC"
    ).fetchall()
    return [_row_to_info(row) for row in rows]


# ---------------------------------------------------------------- 上传
@router.post("/upload", response_model=UploadResult, summary="上传文件")
async def upload_file(
    # File(...) 表示从 multipart 里取字段名为 file 的那一段
    file: UploadFile = File(..., description="待上传的单个文件"),
    user: str = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> UploadResult:
    """POST /api/upload —— 流式落盘 + SHA-256 去重（秒传）。

    之所以是 ``async def``：``UploadFile.read()`` 是异步接口。这也带来了
    「依赖在线程池建连接、函数体在事件循环用连接」的跨线程情况，因此
    db.connect() 关掉了 SQLite 的线程校验（见 db.py 的说明）。

    步骤：
        1. 清洗原始名，生成 UUID 存储名，确定磁盘路径；
        2. 分块读取请求体并写入磁盘，同时累计大小做上限检查；
        3. 用 C++ 扩展（或 Python 回退）计算 SHA-256；
        4. 若库里已有同样哈希的记录，删掉本次副本并返回已有记录（秒传）；
        5. 否则插入元数据并回读，返回给前端。
    """
    config.ensure_dirs()
    original = sanitize_name(file.filename or "unnamed")
    suffix = Path(original).suffix[:16]
    stored = f"{uuid.uuid4().hex}{suffix}"          # 磁盘名：绝不与原名相同
    target = config.UPLOAD_DIR / stored

    size = 0
    try:
        # 关键点：不是 await file.read() 一次性读全，而是 1 MiB 一块地搬运，
        # 因此上传 1 GB 文件时进程内存占用依然是常数级。
        with open(target, "wb") as out:
            while True:
                chunk = await file.read(config.UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024} MiB",
                    )
                out.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)  # 超限：清掉半成品
        raise
    except Exception as exc:  # 磁盘或读取异常
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"写入失败: {exc}") from exc
    finally:
        await file.close()

    # 引擎选择：装了 C++ 扩展就走 C++，否则用 hashlib，对调用方完全透明
    digest = sha256_file(target)

    # 秒传：内容完全相同的文件此前已存在，删除本次副本，复用已有记录。
    existing = conn.execute(
        "SELECT id, filename, original_name, size, sha256, uploader, uploaded_at FROM files WHERE sha256 = ?",
        (digest,),
    ).fetchone()
    if existing is not None:
        target.unlink(missing_ok=True)
        log_activity(conn, "共享了文件", user, "file", existing["id"], existing["original_name"])
        return UploadResult(
            file=_row_to_info(existing),
            duplicate=True,
            engine=ENGINE,
            ok=True,
        )

    cur = conn.execute(
        "INSERT INTO files (filename, original_name, size, sha256, uploader) VALUES (?, ?, ?, ?, ?)",
        (stored, original, size, digest, user),
    )
    row = conn.execute(
        "SELECT id, filename, original_name, size, sha256, uploader, uploaded_at FROM files WHERE id = ?",
        (int(cur.lastrowid),),
    ).fetchone()
    log_activity(conn, "上传了文件", user, "file", int(cur.lastrowid), original)
    return UploadResult(file=_row_to_info(row), duplicate=False, engine=ENGINE, ok=True)


# ---------------------------------------------------------------- 下载
@router.get("/download/{filename}", summary="下载文件")
def download_file(filename: str, conn: sqlite3.Connection = Depends(db_dependency)):
    """GET /api/download/{filename} —— 按存储名取文件，用原始名作为下载文件名。

    路径参数 ``filename`` 必须先在数据库里查到记录才允许读盘；
    随后再用 ``Path.resolve()`` 确认最终路径确实位于 uploads/ 之内，
    两道关卡共同挡住 ``/api/download/../../app.db`` 这类请求（返回 404）。

    FileResponse 会自行处理 Range 断点续传、Content-Length 与
    Content-Disposition: attachment; filename=... （中文名自动编码）。
    """
    row = conn.execute(
        "SELECT filename, original_name FROM files WHERE filename = ?", (filename,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="文件记录不存在")

    path = (config.UPLOAD_DIR / row["filename"]).resolve()
    # 双保险：确保最终路径确实位于上传目录内
    if config.UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="文件已丢失")
    return FileResponse(path, filename=row["original_name"])


# ---------------------------------------------------------------- 元数据
@router.get("/files/{file_id}", response_model=FileInfo, summary="获取单个文件元数据")
def get_file(file_id: int, conn: sqlite3.Connection = Depends(db_dependency)) -> FileInfo:
    """GET /api/files/{id} —— 单个文件的元数据，不存在返回 404。"""
    row = conn.execute(
        "SELECT id, filename, original_name, size, sha256, uploader, uploaded_at FROM files WHERE id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"文件 {file_id} 不存在")
    return _row_to_info(row)


# ---------------------------------------------------------------- 删除
@router.delete("/files/{file_id}", response_model=DeleteResult, summary="删除文件")
def delete_file(file_id: int, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(db_dependency)) -> DeleteResult:
    """DELETE /api/files/{id} —— 先删磁盘文件再删数据库记录。

    ``missing_ok=True`` 让「记录在但文件已被手工删掉」的情况也能正常清理。
    """
    row = conn.execute("SELECT filename, original_name FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"文件 {file_id} 不存在")
    (config.UPLOAD_DIR / row["filename"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    log_activity(conn, "删除了文件", user, "file", file_id, row["original_name"])
    return DeleteResult(detail=f"已删除 {row['original_name']}")
