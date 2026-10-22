"""请求 / 响应数据模型（即各 HTTP 接口的请求体与响应体结构）。

这些类同时承担三件事：
    1. 请求体校验 —— 例如 PostCreate 的 title 为空会直接得到 422 响应；
    2. 响应序列化 —— response_model 决定字段白名单与 /docs 的展示；
    3. 自动生成文档 —— /docs 里的请求/响应示例直接取自这里的字段声明。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ 博客
class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="文章标题")
    content: str = Field(..., min_length=1, description="文章正文")


class PostSummary(BaseModel):
    id: int
    title: str
    author: str = ""
    created_at: str
    excerpt: str


class Post(PostSummary):
    content: str


# ------------------------------------------------------------------ 文件
class FileInfo(BaseModel):
    id: int
    filename: str
    original_name: str
    size: int
    sha256: Optional[str] = None
    uploader: str = ""
    uploaded_at: str
    download_url: str


class UploadResult(BaseModel):
    ok: bool = True
    file: FileInfo
    duplicate: bool = Field(
        False, description="同一 SHA-256 的文件此前已存在，本次为秒传（未重复落盘）"
    )
    engine: str = Field("python", description="计算哈希所用引擎：cpp 或 python")


class DeleteResult(BaseModel):
    ok: bool = True
    detail: str = ""


class HealthInfo(BaseModel):
    status: str
    version: str
    modules: List[str]
    cpp_extension: str
    cpp_available: bool


# ------------------------------------------------------------------ 身份
class IdentityRequest(BaseModel):
    """POST /api/login 的请求体：只需要一个昵称。

    这里没有密码字段——本站不做身份核验，昵称只用于区分「谁说的/谁做的」。
    """

    username: str = Field(..., min_length=1, max_length=24, description="你的昵称")


class IdentityInfo(BaseModel):
    name: str
    session_days: int = 30


class LoginResult(BaseModel):
    ok: bool = True
    user: IdentityInfo
    expires_in: int = Field(..., description="身份有效期（秒）")


class SessionInfo(BaseModel):
    """GET /api/session —— 前端据此显示当前昵称或跳转登记页。"""

    authenticated: bool
    user: Optional[IdentityInfo] = None
    session_days: int = 30


# ------------------------------------------------------------------ 小组协作
class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field("", max_length=4000)
    status: Literal["todo", "doing", "done"] = "todo"
    priority: Literal["low", "medium", "high"] = "medium"
    assignee: str = Field("", max_length=64, description="负责人，可留空")
    due_date: Optional[str] = Field(None, max_length=32)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    status: Optional[Literal["todo", "doing", "done"]] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    assignee: Optional[str] = Field(None, max_length=64)
    due_date: Optional[str] = Field(None, max_length=32)


class PollCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    options: List[str] = Field(..., min_length=2, max_length=8)
    ends_at: Optional[str] = Field(None, max_length=32)


class VoteCreate(BaseModel):
    option_id: int = Field(..., gt=0)
