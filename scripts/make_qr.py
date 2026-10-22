"""把任意网址生成一张二维码 PNG，方便手机扫码访问。

用法：
    .venv\\Scripts\\python.exe scripts\\make_qr.py <网址> [输出路径]

默认输出 docs\\公网访问二维码.png。
依赖（仅本脚本使用，不参与网站运行）：pip install qrcode pillow
"""

from __future__ import annotations

import sys
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    url = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "docs" / "公网访问二维码.png"
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=10, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#10182b", back_color="white")
    image.save(out)
    print(f"已生成 {out.relative_to(ROOT)}（内容：{url}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
