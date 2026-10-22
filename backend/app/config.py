"""集中配置。

所有路径与运行参数都可以通过环境变量覆盖，便于在本机、局域网或外网
部署时使用同一份代码。
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 目录结构
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _path_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser().resolve() if raw else default


DATA_DIR = _path_env("APP_DATA_DIR", BACKEND_DIR / "data")
UPLOAD_DIR = _path_env("APP_UPLOAD_DIR", BACKEND_DIR / "uploads")
FRONTEND_DIR = _path_env("APP_FRONTEND_DIR", PROJECT_ROOT / "frontend")
DB_PATH = _path_env("APP_DB_PATH", DATA_DIR / "app.db")

# ---------------------------------------------------------------- 网络参数
# 默认监听 0.0.0.0，这样本机（127.0.0.1:8000）、局域网、以及做了端口映射的
# 外网访问都使用同一个进程。仅需本机访问时可设 APP_HOST=127.0.0.1。
#
# 注意：这里的 HOST/PORT 只影响 `python -m backend.app.main` 这种自启动方式；
# 用 uvicorn 命令行（scripts/start.ps1）启动时，真正生效的是命令行的
# --host/--port，本文件的值仅用于打印日志与运维参考。
HOST = os.getenv("APP_HOST", "0.0.0.0")
PORT = int(os.getenv("APP_PORT", "8000"))
RELOAD = os.getenv("APP_RELOAD", "0") not in ("0", "", "false", "False")

# ---------------------------------------------------------------- 业务限额
# 单文件上传上限，默认 512 MiB。上传采用流式分块写入，内存占用与文件大小无关。
MAX_UPLOAD_BYTES = int(os.getenv("APP_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB

# 房间内存历史：用于新加入的客户端补齐上下文。0 表示不保留。
CANVAS_HISTORY_LIMIT = int(os.getenv("APP_CANVAS_HISTORY_LIMIT", "5000"))
CHAT_HISTORY_LIMIT = int(os.getenv("APP_CHAT_HISTORY_LIMIT", "200"))

# 允许跨域访问的来源，"*" 表示不限制（本地工具类应用默认放开）。
# 只在「前端页面与接口不同源」时才起作用（例如把前端放到 5173 端口另开服务）；
# 本项目前端由同一个服务托管，属于同源请求，默认值即可。
CORS_ORIGINS = [o.strip() for o in os.getenv("APP_CORS_ORIGINS", "*").split(",") if o.strip()]

# ---------------------------------------------------------------- 身份
# 本站采用「昵称门禁」：进入网站只需登记一个昵称，不做任何核验。
# 相关逻辑见 backend/app/auth.py；昵称有效期固定 30 天。

# 身份 Cookie 的签名密钥。留空则自动生成并保存到 backend/data/.identity_secret，
# 重启后已登记的设备不需要重新登记。
SECRET = os.getenv("APP_SECRET", "").strip()


def ensure_dirs() -> None:
    """确保数据目录与上传目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def describe() -> dict:
    """返回一份可直接打印的配置摘要，启动时输出便于排错。"""
    return {
        "backend_dir": str(BACKEND_DIR),
        "frontend_dir": str(FRONTEND_DIR),
        "db_path": str(DB_PATH),
        "upload_dir": str(UPLOAD_DIR),
        "host": HOST,
        "port": PORT,
        "max_upload_mb": round(MAX_UPLOAD_BYTES / 1024 / 1024, 1),
    }
