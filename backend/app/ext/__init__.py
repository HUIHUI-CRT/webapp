"""C++ 扩展加载器（带回退）。

加载顺序：
    1. 直接 ``import fastcore``（已安装或位于 sys.path 上）。
    2. 把常见编译产物目录加入 ``sys.path`` 后再试一次，例如
       ``backend/build``、``backend/app/ext``、项目根目录。
    3. 全部失败则使用 :mod:`backend.app.ext.fallback` 的纯 Python 实现。

对外始终暴露同一组函数与 ``ENGINE`` 常量。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List, Union

from .. import config
from . import fallback

_SEARCH_DIRS = [
    config.BACKEND_DIR / "build",
    config.BACKEND_DIR / "build" / "lib",
    config.BACKEND_DIR / "app" / "ext",
    config.BACKEND_DIR,
]

_cpp_module = None
_load_error: str | None = None


def _try_load():
    global _cpp_module, _load_error
    for extra in _SEARCH_DIRS:
        if extra.is_dir() and str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    try:
        import fastcore  # type: ignore

        _cpp_module = fastcore
        _load_error = None
    except Exception as exc:  # pragma: no cover - 取决于本机是否编译
        _cpp_module = None
        _load_error = f"{type(exc).__name__}: {exc}"


_try_load()

ENGINE = "cpp" if _cpp_module is not None else "python"
AVAILABLE = _cpp_module is not None


def reload_extension() -> bool:
    """重新尝试加载（编译完成后无需重启进程即可热加载）。"""
    _try_load()
    global ENGINE, AVAILABLE
    ENGINE = "cpp" if _cpp_module is not None else "python"
    AVAILABLE = _cpp_module is not None
    return AVAILABLE


def status() -> dict:
    return {
        "engine": ENGINE,
        "available": AVAILABLE,
        "detail": _load_error or ("fastcore 已加载" if AVAILABLE else "未找到扩展，使用 Python 回退"),
    }


def sha256_file(path: Union[str, Path]) -> str:
    """计算文件 SHA-256（分块流式，大文件不会吃满内存）。"""
    if _cpp_module is not None:
        return _cpp_module.sha256_file(str(path))
    return fallback.sha256_file(path)


def merge_chunks(paths: Iterable[Union[str, Path]], output: Union[str, Path]) -> int:
    """按顺序合并分块文件。"""
    items: List[str] = [str(p) for p in paths]
    if _cpp_module is not None:
        return int(_cpp_module.merge_chunks(items, str(output)))
    return fallback.merge_chunks(items, output)
