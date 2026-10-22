"""构建期兼容补丁（仅通过 PYTHONPATH 在本机构建命令中生效）。

背景：
    Python 3.14 在 Windows 上会把 ``os.mkdir(path, mode)`` 的 mode 参数翻译成
    目录的访问权限。``tempfile.mkdtemp()`` 内部使用 ``os.mkdir(path, 0o700)``，
    生成的目录只允许属主访问；当构建命令运行在受限令牌（沙箱用户）下时，
    该目录随即变成不可写，pip 等工具会以
    ``PermissionError: [Errno 13]`` 失败。

处理：
    用不带 mode 参数的 ``os.mkdir`` 重新实现 ``mkdtemp``，权限走系统默认，
    其余语义（前缀、后缀、目录、重试）与标准库保持一致。

本文件不参与网站运行，只服务于本机的依赖安装与测试命令。
"""

from __future__ import annotations

import os
import tempfile

_TMP_MAX = getattr(tempfile, "TMP_MAX", 10000)


def mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
    prefix = prefix or tempfile.gettempprefix()
    suffix = suffix or ""
    directory = dir or tempfile.gettempdir()
    names = tempfile._get_candidate_names()  # type: ignore[attr-defined]
    last = None
    for _ in range(_TMP_MAX):
        path = os.path.join(directory, prefix + next(names) + suffix)
        try:
            os.mkdir(path)  # 关键：不传 mode，避免 0o700 变成仅属主可访问
            return os.path.abspath(path)
        except FileExistsError as exc:
            last = exc
            continue
    raise FileExistsError(f"无法创建临时目录，重试 {_TMP_MAX} 次后仍失败") from last


tempfile.mkdtemp = mkdtemp  # type: ignore[assignment]

# 供人工确认补丁确实加载
os.environ.setdefault("DSH_TEMPFILE_PATCH", "1")
