#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

STOP_POSTGRES=1
if [ "${1:-}" = "--keep-postgres" ]; then
  STOP_POSTGRES=0
elif [ -n "${1:-}" ]; then
  echo "用法：bash scripts/dev_down.sh [--keep-postgres]"
  exit 1
fi

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

stop_pid_safely() {
  local pid="$1"
  local cmd

  cmd="$(pid_cmdline "$pid")"
  if [ -z "$cmd" ]; then
    return 0
  fi

  echo "[dev_down] 正在结束进程 PID=$pid"
  echo "[dev_down] 进程命令：$cmd"

  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..8}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done

  echo "[dev_down] 进程未正常退出，执行强制结束 PID=$pid"
  kill -KILL "$pid" 2>/dev/null || true

  for _ in {1..3}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done

  echo "[dev_down] 无法结束 PID=$pid，请手工处理。"
  return 1
}

declare -A port_pid_map=()
while IFS= read -r pid; do
  [ -n "$pid" ] || continue
  port_pid_map["$pid"]=1
done < <(get_port_8000_pids || true)

declare -A candidate_map=()
while IFS= read -r pid; do
  [ -n "$pid" ] || continue
  candidate_map["$pid"]=1
done < <(pgrep -f "app.main:app" || true)

for pid in "${!port_pid_map[@]}"; do
  candidate_map["$pid"]=1
done

declare -A target_map=()
for pid in "${!candidate_map[@]}"; do
  cmd="$(pid_cmdline "$pid")"
  [ -n "$cmd" ] || continue

  if [[ "$cmd" == *"app.main:app"* ]]; then
    target_map["$pid"]="$cmd"
    continue
  fi

  if [ "${port_pid_map[$pid]+x}" ] && [[ "$cmd" == *"python"* || "$cmd" == *"uvicorn"* ]]; then
    target_map["$pid"]="$cmd"
  fi
done

if [ "${#target_map[@]}" -eq 0 ]; then
  echo "[dev_down] 未检测到需要停止的本地 uvicorn 进程。"
else
  for pid in "${!target_map[@]}"; do
    stop_pid_safely "$pid"
  done
fi

if [ "$STOP_POSTGRES" -eq 1 ]; then
  if docker compose stop postgres >/dev/null 2>&1; then
    echo "[dev_down] postgres 已停止。"
  else
    echo "[dev_down] postgres 未运行或停止失败，可忽略。"
  fi
else
  echo "[dev_down] 已保留 postgres（--keep-postgres）。"
fi

rm -f "$PROJECT_ROOT/logs/dev_web.pid"

echo "本地环境已停止"
