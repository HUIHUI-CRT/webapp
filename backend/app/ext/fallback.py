"""纯 Python 回退实现。

当 C++ 扩展未编译或导入失败时，后端自动使用这里的函数，接口与 C++ 版本
完全一致，因此上层代码无需关心运行在哪个引擎上。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Iterable, List, Union

ENGINE = "python"
CHUNK = 1024 * 1024


def sha256_file(path: Union[str, Path]) -> str:
    """流式计算文件的 SHA-256，内存占用恒定。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def merge_chunks(paths: Iterable[Union[str, Path]], output: Union[str, Path]) -> int:
    """按给定顺序把多个分块文件合并为一个文件，返回写入字节数。"""
    total = 0
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as out:
        for item in paths:
            with open(item, "rb") as src:
                while True:
                    block = src.read(CHUNK)
                    if not block:
                        break
                    out.write(block)
                    total += len(block)
    return total


def copy_file(src: Union[str, Path], dst: Union[str, Path]) -> int:
    """分块复制文件（用于上传落盘的流式写入），返回字节数。"""
    shutil.copyfile(str(src), str(dst))
    return Path(dst).stat().st_size
