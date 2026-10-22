"""构建期小工具：在保留 UTF-8 BOM 的前提下修改 PowerShell 脚本。

Windows PowerShell 5.1 依赖 BOM 才能把 .ps1 里的中文按 UTF-8 解码，
用普通编辑器改写后 BOM 容易丢失，这里统一走本脚本。

用法：
    python .tools/patch_ps1.py <文件> "<旧文本>" "<新文本>"
"""

from __future__ import annotations

import sys
from pathlib import Path


def patch(path: Path, old: str, new: str) -> int:
    text = path.read_text(encoding="utf-8-sig")
    if old not in text:
        print(f"未找到待替换内容: {old!r}")
        return 1
    text = text.replace(old, new)
    path.write_text("\ufeff" + text, encoding="utf-8", newline="")
    print(f"已更新 {path}（保留 BOM）")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(patch(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
