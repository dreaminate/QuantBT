#!/usr/bin/env bash
# QuantBT 一键启动（macOS / Linux）
# 等价于 Windows 的 start-qb.ps1：后端后台跑 uvicorn :8000，前端前台跑 vite :5173。
# 按 Ctrl+C 结束前端后会一并停掉后端。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# 全新机兜底：保证 ~/.quantbt 存在（keystore 索引 / secrets 会写这里）
mkdir -p "$HOME/.quantbt"

# 优先用 backend/.venv 里的解释器，没有就退回系统 python3 / python
if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  BACKEND_PYTHON="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  BACKEND_PYTHON="python3"
else
  BACKEND_PYTHON="python"
fi

# 后端：后台运行（监听 127.0.0.1:8000）
(
  cd "$BACKEND_DIR"
  exec "$BACKEND_PYTHON" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

# 前端退出时（含 Ctrl+C）一并收掉后端。
# 给 uvicorn 的 reload supervisor 发 SIGTERM，它会自行优雅停掉 worker 子进程。
# （注意：后台子 shell 与本脚本同进程组，故不能用 kill -- -PGID，会连自己一起杀。）
cleanup() {
  if kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "qb backend (后台): http://127.0.0.1:8000  (pid $BACKEND_PID)"
echo "qb frontend (当前窗口): http://127.0.0.1:5173"
echo ""

# 前端：当前终端前台运行；Ctrl+C 结束 vite → 触发 cleanup 收后端
cd "$FRONTEND_DIR"
npm run dev -- --host 127.0.0.1 --port 5173
