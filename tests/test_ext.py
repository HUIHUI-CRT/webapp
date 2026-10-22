"""C++ 扩展验收：编译产物与纯 Python 回退结果一致。"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from backend.app import config
from backend.app.ext import ENGINE, fallback, sha256_file, status

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "backend" / "build"


def _sample(path: Path, size: int = 300_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes((i * 31 + 7) % 256 for i in range(size)))
    return path


def test_engine_is_reported():
    info = status()
    assert info["engine"] in {"cpp", "python"}
    assert isinstance(info["available"], bool)


def test_sha256_matches_hashlib(sandbox):
    sample = _sample(sandbox / "hash.bin")
    expected = hashlib.sha256(sample.read_bytes()).hexdigest()
    assert sha256_file(sample) == expected
    assert fallback.sha256_file(sample) == expected


def test_merge_chunks_matches_direct_concat(sandbox):
    parts_dir = sandbox / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    blobs = [bytes([n]) * (1000 + n) for n in range(1, 5)]
    paths = []
    for index, blob in enumerate(blobs):
        part = parts_dir / f"part{index}.bin"
        part.write_bytes(blob)
        paths.append(part)

    merged = sandbox / "merged.bin"
    written = __import__("backend.app.ext", fromlist=["merge_chunks"]).merge_chunks(paths, merged)
    assert written == sum(len(b) for b in blobs)
    assert merged.read_bytes() == b"".join(blobs)


@pytest.mark.skipif(not BUILD_DIR.is_dir(), reason="尚未编译 C++ 扩展")
def test_cpp_module_is_importable_and_correct(sandbox):
    if str(BUILD_DIR) not in sys.path:
        sys.path.insert(0, str(BUILD_DIR))
    try:
        import fastcore  # type: ignore
    except ImportError:
        pytest.skip("C++ 扩展未编译")

    sample = _sample(sandbox / "cpp-hash.bin", 120_000)
    assert fastcore.sha256_file(str(sample)) == hashlib.sha256(sample.read_bytes()).hexdigest()
    assert fastcore.engine() == "cpp"

    parts = []
    for index in range(3):
        part = sandbox / f"cpp-part{index}.bin"
        part.write_bytes(bytes([index]) * 5000)
        parts.append(str(part))
    out = sandbox / "cpp-merged.bin"
    assert fastcore.merge_chunks(parts, str(out)) == 15000
    assert out.read_bytes() == b"".join(bytes([i]) * 5000 for i in range(3))


def test_fallback_works_without_extension(sandbox):
    """即使扩展不可用，回退实现也必须可用（对应风险表中的编译环境缺失）。"""
    sample = _sample(sandbox / "fallback.bin", 50_000)
    assert fallback.sha256_file(sample) == hashlib.sha256(sample.read_bytes()).hexdigest()
    assert fallback.ENGINE == "python"
    assert config.UPLOAD_DIR.is_dir()
