#!/usr/bin/env bash
# Linux / macOS / Git Bash 下的启动脚本，与 scripts/start.ps1 等价。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BIND_HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-8000}"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "未找到 .venv，正在创建虚拟环境..."
  python3 -m venv .venv
  PY="$ROOT/.venv/bin/python"
fi

if ! "$PY" -c "import fastapi, uvicorn, multipart" >/dev/null 2>&1; then
  echo "依赖不完整，正在安装 requirements.txt ..."
  "$PY" -m pip install --disable-pip-version-check -r requirements.txt
fi

echo "本机访问   http://127.0.0.1:${PORT}/index.html"
for ip in $(hostname -I 2>/dev/null || true); do
  echo "局域网访问 http://${ip}:${PORT}/index.html"
done
echo "接口文档   http://127.0.0.1:${PORT}/docs"

exec "$PY" -m uvicorn backend.app.main:app --host "$BIND_HOST" --port "$PORT"
