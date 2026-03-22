#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/dev_web.log"
PID_FILE="$LOG_DIR/dev_web.pid"
WEB_URL="http://127.0.0.1:8000/admin/home"
DOCS_URL="http://127.0.0.1:8000/docs"
HEALTH_URL="http://127.0.0.1:8000/healthz"

mkdir -p "$LOG_DIR"

if [ ! -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
  echo "[dev_up] 未找到 .venv，请先创建虚拟环境后重试。"
  exit 1
fi
source "$PROJECT_ROOT/.venv/bin/activate"

for required_cmd in docker uvicorn alembic curl; do
  if ! command -v "$required_cmd" >/dev/null 2>&1; then
    echo "[dev_up] 未检测到 $required_cmd，请先安装依赖后重试。"
    exit 1
  fi
done

get_port_8000_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null | sort -u
    return
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -lptn 'sport = :8000' 2>/dev/null \
      | awk -F 'pid=' 'NR>1 && NF>1 {split($2, a, ","); print a[1]}' \
      | sort -u
  fi
}

pid_cmdline() {
  ps -p "$1" -o args= 2>/dev/null | sed 's/^[[:space:]]*//' || true
}

pid_cwd() {
  readlink "/proc/$1/cwd" 2>/dev/null || true
}

is_project_uvicorn_pid() {
  local pid="$1"
  local cmd cwd

  cmd="$(pid_cmdline "$pid")"
  cwd="$(pid_cwd "$pid")"

  [[ -n "$cmd" && "$cmd" == *"uvicorn"* && "$cmd" == *"app.main:app"* && "$cwd" == "$PROJECT_ROOT" ]]
}

stop_pid_safely() {
  local pid="$1"
  local cmd

  cmd="$(pid_cmdline "$pid")"
  if [ -z "$cmd" ]; then
    return 0
  fi

  echo "[dev_up] 端口 8000 被占用，正在结束残留进程 PID=$pid"
  echo "[dev_up] 进程命令：$cmd"

  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..8}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done

  echo "[dev_up] 进程未在超时内退出，执行强制结束 PID=$pid"
  kill -KILL "$pid" 2>/dev/null || true

  for _ in {1..3}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done

  echo "[dev_up] 无法结束 PID=$pid，请手工处理后重试。"
  return 1
}

wait_postgres_ready() {
  local container_id health

  container_id="$(docker compose ps -q postgres || true)"
  if [ -z "$container_id" ]; then
    echo "[dev_up] 无法找到 postgres 容器，请检查 docker compose 配置。"
    return 1
  fi

  echo "[dev_up] 等待 postgres 可用..."
  for _ in {1..120}; do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"

    if [ "$health" = "healthy" ]; then
      echo "[dev_up] postgres 已可用。"
      return 0
    fi

    if [ "$health" = "none" ] && command -v nc >/dev/null 2>&1; then
      if nc -z 127.0.0.1 5432 >/dev/null 2>&1; then
        echo "[dev_up] postgres 5432 端口已可连接。"
        return 0
      fi
    fi

    sleep 1
  done

  echo "[dev_up] 等待 postgres 超时，请检查容器状态。"
  docker compose ps postgres || true
  return 1
}

print_access_info() {
  echo "Web 地址：$WEB_URL"
  echo "Docs 地址：$DOCS_URL"
}

echo "[dev_up] 启动 postgres..."
docker compose up -d postgres
wait_postgres_ready

echo "[dev_up] 执行数据库迁移..."
alembic upgrade head

mapfile -t port_pids < <(get_port_8000_pids || true)
if [ "${#port_pids[@]}" -gt 0 ]; then
  for pid in "${port_pids[@]}"; do
    if is_project_uvicorn_pid "$pid"; then
      echo "[dev_up] 检测到本项目 Web 已在运行（PID=$pid），跳过重复启动。"
      print_access_info
      if command -v xdg-open >/dev/null 2>&1; then
        (xdg-open "$WEB_URL" >/dev/null 2>&1 || true)
      fi
      exit 0
    fi
  done

  for pid in "${port_pids[@]}"; do
    cmd="$(pid_cmdline "$pid")"
    if [[ "$cmd" == *"python"* || "$cmd" == *"uvicorn"* ]]; then
      stop_pid_safely "$pid"
      continue
    fi

    echo "[dev_up] 端口 8000 被非 Python/Uvicorn 进程占用，无法自动处理。"
    echo "[dev_up] PID=$pid, 命令：$cmd"
    exit 1
  done
fi

echo "[dev_up] 后台启动 Web 服务，日志输出到 $LOG_FILE"
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 >>"$LOG_FILE" 2>&1 &
web_pid=$!
echo "$web_pid" > "$PID_FILE"

for _ in {1..60}; do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "[dev_up] Web 启动成功。"
    print_access_info
    if command -v xdg-open >/dev/null 2>&1; then
      (xdg-open "$WEB_URL" >/dev/null 2>&1 || true)
    fi
    exit 0
  fi

  if ! kill -0 "$web_pid" 2>/dev/null; then
    break
  fi

  sleep 1
done

echo "[dev_up] Web 启动失败，请查看日志：$LOG_FILE"
tail -n 60 "$LOG_FILE" || true
exit 1
