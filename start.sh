#!/usr/bin/env bash
# 本地开发环境启动脚本
#
# 用法：
#   ./start.sh         启动 Postgres / 后端 / 前端
#   ./start.sh stop    停止后端 / 前端
#   ./start.sh logs    跟踪后端 + 前端日志
#   ./start.sh status  查看进程与端口状态

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/tmp/self-learning-system"
mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

c_green() { printf "\033[32m%s\033[0m" "$1"; }
c_red()   { printf "\033[31m%s\033[0m" "$1"; }
c_dim()   { printf "\033[2m%s\033[0m" "$1"; }

stop_all() {
  pkill -f "uvicorn app.main" 2>/dev/null && echo "  $(c_dim 已停止后端)" || true
  pkill -f "vite"             2>/dev/null && echo "  $(c_dim 已停止前端)" || true
}

show_status() {
  echo "进程："
  pgrep -af "uvicorn app.main" >/dev/null \
    && echo "  $(c_green 后端 ✓) $(pgrep -af 'uvicorn app.main' | head -1)" \
    || echo "  $(c_red 后端 ✗)"
  pgrep -af "vite" >/dev/null \
    && echo "  $(c_green 前端 ✓) $(pgrep -af 'vite' | head -1)" \
    || echo "  $(c_red 前端 ✗)"
  echo "端点："
  curl -sf -o /dev/null http://localhost:8000/api/health \
    && echo "  $(c_green 8000) /api/health 通" \
    || echo "  $(c_red 8000) /api/health 不通"
  curl -sf -o /dev/null http://localhost:5173/ \
    && echo "  $(c_green 5173) 前端 通" \
    || echo "  $(c_red 5173) 前端 不通"
}

case "${1:-start}" in
  stop)
    echo "→ 停止服务"
    stop_all
    exit 0
    ;;
  logs)
    echo "→ 跟踪日志（Ctrl+C 退出，不会停服务）"
    exec tail -F "$BACKEND_LOG" "$FRONTEND_LOG"
    ;;
  status)
    show_status
    exit 0
    ;;
  start) ;;
  *)
    echo "用法: $0 [start|stop|logs|status]" >&2
    exit 1
    ;;
esac

# ---------- start ----------

if ! pg_isready -q 2>/dev/null; then
  echo "→ 启动 Postgres"
  sudo service postgresql start
fi

echo "→ 清理旧进程"
stop_all
sleep 1

echo "→ 启动后端 → $BACKEND_LOG"
cd "$ROOT/backend"
nohup .venv/bin/uvicorn app.main:app --port 8000 --host 0.0.0.0 \
  >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo "→ 启动前端 → $FRONTEND_LOG"
cd "$ROOT/frontend"
nohup npm run dev >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

cd "$ROOT"

# 等后端 health
printf "→ 等后端就绪"
for i in $(seq 1 20); do
  if curl -sf -o /dev/null http://localhost:8000/api/health 2>/dev/null; then
    printf " $(c_green ✓)\n"
    break
  fi
  printf "."
  sleep 1
  if [ "$i" = "20" ]; then
    printf " $(c_red 超时)\n"
    echo "  查日志: tail $BACKEND_LOG"
    exit 1
  fi
done

# 等前端 ready（vite 启动很快，但首次 npm install 后会慢）
printf "→ 等前端就绪"
for i in $(seq 1 20); do
  if curl -sf -o /dev/null http://localhost:5173/ 2>/dev/null; then
    printf " $(c_green ✓)\n"
    break
  fi
  printf "."
  sleep 1
done

echo ""
echo "$(c_green ✓ 全部就绪)"
echo "  后端  http://localhost:8000  pid=$BACKEND_PID"
echo "  前端  http://localhost:5173  pid=$FRONTEND_PID"
echo ""
echo "  $(c_dim 查日志: ./start.sh logs)"
echo "  $(c_dim 停服务: ./start.sh stop)"
echo "  $(c_dim 看状态: ./start.sh status)"
