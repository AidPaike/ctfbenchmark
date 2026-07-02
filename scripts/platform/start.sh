#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Configuration ──────────────────────────────────────────────────
export PYTHONPATH="${PYTHONPATH:-}:${PROJECT_ROOT}/backend:${PROJECT_ROOT}/sdk"
export DROPLET_WORK_ROOT="${DROPLET_WORK_ROOT:-${PROJECT_ROOT}/data/work}"
export DROPLET_PUBLIC_HOST="${DROPLET_PUBLIC_HOST:-127.0.0.1}"
export DROPLET_DATABASE_PATH="${DROPLET_DATABASE_PATH:-${PROJECT_ROOT}/data/droplet.db}"
export DROPLET_PRESTART_CHALLENGES="${DROPLET_PRESTART_CHALLENGES:-0}"
export DROPLET_API_TOKEN="${DROPLET_API_TOKEN:-droplet_dev_admin}"
export FORCE_COLOR="1"                          # keep ANSI colors in log files

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-1349}"
FRONTEND_PORT="${FRONTEND_PORT:-10349}"
VERSION="0.6.0"

# Proxy settings
if [[ -n "${DROPLET_DOCKER_PROXY:-}" ]]; then
  export HTTP_PROXY="${HTTP_PROXY:-$DROPLET_DOCKER_PROXY}"
  export HTTPS_PROXY="${HTTPS_PROXY:-$DROPLET_DOCKER_PROXY}"
  export http_proxy="${http_proxy:-$DROPLET_DOCKER_PROXY}"
  export https_proxy="${https_proxy:-$DROPLET_DOCKER_PROXY}"
fi
if [[ -n "${DROPLET_DOCKER_NO_PROXY:-}" ]]; then
  export NO_PROXY="${NO_PROXY:-$DROPLET_DOCKER_NO_PROXY}"
  export no_proxy="${no_proxy:-$DROPLET_DOCKER_NO_PROXY}"
fi

# ── Helpers ────────────────────────────────────────────────────────
_pidfile_backend="${PROJECT_ROOT}/.droplet-backend.pid"
_pidfile_frontend="${PROJECT_ROOT}/.droplet-frontend.pid"
LOG_DIR="${PROJECT_ROOT}/logs"
BACKEND_LOG="${LOG_DIR}/backend.log"
BACKEND_PID=""
FRONTEND_PID=""

_process_group_id() {
  local pid="$1"
  ps -o pgid= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true
}

_is_droplet_process() {
  local pid="$1"
  local cmdline
  local cwd=""
  if [[ -f "/proc/$pid/cmdline" ]]; then
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
  else
    cmdline=$(ps -p "$pid" -o args= 2>/dev/null || true)
  fi

  if [[ "$cmdline" == *"uvicorn"*"droplet.app:app"* ]] && \
     { [[ -z "$cwd" ]] || [[ "$cwd" == "$PROJECT_ROOT"* ]]; }; then
    return 0
  fi
  if { [[ "$cmdline" == *"npm"*"run"*"dev"* ]] || [[ "$cmdline" == *"vite"*"--host"* ]]; } && \
     { [[ -z "$cwd" ]] || [[ "$cwd" == "$PROJECT_ROOT/frontend"* ]]; }; then
    return 0
  fi
  return 1
}

_kill_started_process() {
  local pid="$1"
  local name="$2"
  local pgid
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return
  fi
  pgid="$(_process_group_id "$pid")"
  if [[ -n "$pgid" ]]; then
    kill -- -"$pgid" 2>/dev/null || true
  else
    kill "$pid" 2>/dev/null || true
  fi
  for _ in {1..10}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo -e "\e[33m[WARN]\e[0m $name did not exit gracefully, forcing ..."
    if [[ -n "$pgid" ]]; then
      kill -9 -- -"$pgid" 2>/dev/null || true
    fi
    kill -9 "$pid" 2>/dev/null || true
  fi
}

_cleanup_started_processes() {
  _kill_started_process "$BACKEND_PID" "backend"
  _kill_started_process "$FRONTEND_PID" "frontend"
  rm -f "$_pidfile_frontend" "$_pidfile_backend"
}

_wait_for_port_release() {
  local port="$1"
  for _ in {1..20}; do
    if [[ -z "$(lsof -ti:"$port" 2>/dev/null || true)" ]]; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

# ── Stop any existing instances ────────────────────────────────────
bash "${SCRIPT_DIR}/stop.sh" >/dev/null 2>&1 || true

# ── Verify ports are free ──────────────────────────────────────────
_check_port() {
  local port="$1"
  local name="$2"
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    local remaining=()
    for pid in $pids; do
      if _is_droplet_process "$pid"; then
        echo -e "\e[33m[WARN]\e[0m Port $port is held by orphaned Droplet $name (PID: $pid), cleaning it up ..."
        _kill_started_process "$pid" "$name"
      else
        remaining+=("$pid")
      fi
    done

    if [[ "${#remaining[@]}" -gt 0 ]]; then
      if [[ "${DROPLET_FORCE_KILL_PORTS:-0}" != "1" ]]; then
        echo -e "\e[31m[ERROR]\e[0m Port $port is already in use (PID: ${remaining[*]})."
        echo -e "        Stop that process first, or rerun with DROPLET_FORCE_KILL_PORTS=1."
        exit 1
      fi
      echo -e "\e[33m[WARN]\e[0m Port $port is in use (PID: ${remaining[*]}), force killing because DROPLET_FORCE_KILL_PORTS=1 ..."
      for pid in "${remaining[@]}"; do
        kill -9 "$pid" 2>/dev/null || true
      done
    fi

    if ! _wait_for_port_release "$port"; then
      pids=$(lsof -ti:"$port" 2>/dev/null || true)
      echo -e "\e[31m[ERROR]\e[0m Port $port is still in use (PID: $pids)."
      exit 1
    fi
  fi
}
_check_port "$BACKEND_PORT" "backend"
_check_port "$FRONTEND_PORT" "frontend"

mkdir -p "$LOG_DIR"
rm -f "$BACKEND_LOG"

# ── Start frontend in background ───────────────────────────────────
if [[ "${START_FRONTEND:-1}" == "1" ]]; then
  cd "${PROJECT_ROOT}/frontend"
  # Start in a new process group so we can kill the whole tree
  setsid npm run dev >"${LOG_DIR}/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  echo "$FRONTEND_PID" > "$_pidfile_frontend"
fi

# ── Start backend in background ────────────────────────────────────
cd "$PROJECT_ROOT"

# Start in a new process group so we can kill the whole tree
setsid python -m uvicorn droplet.app:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$_pidfile_backend"

# Wait briefly and check if backend started successfully
sleep 2
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo -e "\e[31m[ERROR]\e[0m Backend failed to start. Check logs:"
  tail -5 "$BACKEND_LOG" 2>/dev/null
  _cleanup_started_processes
  exit 1
fi

# ── Terminal scroll-region setup ───────────────────────────────────
# We draw a fixed banner in the top lines and make everything below it
# a scrollable region so request logs never overwrite the banner.

# Detect terminal capabilities
_HAS_TPUT=0
if command -v tput >/dev/null 2>&1 && [[ -t 1 ]]; then
  _HAS_TPUT=1
fi

_ROWS=24
_BANNER_HEIGHT=15

if [[ "$_HAS_TPUT" == "1" ]]; then
  _ROWS=$(tput lines)
fi

# ANSI colour helpers
C() { printf '\033[%sm' "$1"; }
C_RESET=$(C "0")
C_DIM=$(C "2")
C_BOLD=$(C "1")
C_CYAN=$(C "36")
C_GREEN=$(C "32")
C_YELLOW=$(C "33")
C_SPLASH=$(C "1;36")
C_WHITE=$(C "97")

print_banner() {
  local fe_url="http://${BACKEND_HOST}:${FRONTEND_PORT}"
  local be_url="http://${BACKEND_HOST}:${BACKEND_PORT}"
  local ds_path="${DROPLET_DATASET_ROOT:-${PROJECT_ROOT}/datasets}"

  echo ""
  echo -e "       ${C_SPLASH}~  ~${C_RESET}                 ${C_BOLD}${C_CYAN}Droplet${C_RESET}  ${C_DIM}v${VERSION}${C_RESET}"
  echo -e "        ${C_CYAN}.--.${C_RESET}                ${C_DIM}Black-box CTF Benchmark Platform${C_RESET}"
  echo -e "       ${C_CYAN}/    \\ ${C_RESET}"
  echo -e "      ${C_CYAN}| ${C_WHITE}>  <${C_CYAN} |${C_RESET}"
  echo -e "      ${C_CYAN}|  ~~  |${C_RESET}"
  echo -e "       ${C_CYAN}\\ __ /${C_RESET}"
  echo -e "        ${C_CYAN}'--'${C_RESET}"
  echo ""
  echo -e "  ${C_BOLD}Frontend${C_RESET}   ${C_GREEN}${fe_url}${C_RESET}"
  echo -e "  ${C_BOLD}Backend${C_RESET}    ${C_GREEN}${be_url}${C_RESET}"
  echo -e "  ${C_BOLD}Dataset${C_RESET}    ${C_DIM}${ds_path}${C_RESET}"
  echo ""
  echo -e "  ${C_BOLD}Prefetch${C_RESET}   ${C_DIM}启动中...${C_RESET}"
  echo ""
  echo -e "  ${C_DIM}Press Ctrl+C to stop${C_RESET}"
  echo ""
}

# ── Prefetch progress (Python polls API → file, shell reads file → terminal)
_PREFETCH_POLL_PID=""
_PREFETCH_DISPLAY_PID=""
_PREFETCH_STATUS_FILE="/tmp/droplet-prefetch.status"

_start_prefetch_progress() {
  if [[ "$_HAS_TPUT" != "1" ]]; then
    return
  fi
  rm -f "$_PREFETCH_STATUS_FILE"
  echo "启动中..." > "$_PREFETCH_STATUS_FILE"

  # Background: Python polls API, writes status to file
  python3 "${PROJECT_ROOT}/scripts/ops/prefetch-tui.py" \
    "$_PREFETCH_STATUS_FILE" "http://${BACKEND_HOST}:${BACKEND_PORT}" "$DROPLET_API_TOKEN" \
    >/dev/null 2>&1 &
  _PREFETCH_POLL_PID=$!

  # Background: Shell reads file, updates banner line via tput
  (
    local row=12
    local prev=""
    while true; do
      local status
      status=$(cat "$_PREFETCH_STATUS_FILE" 2>/dev/null || echo "...")
      if [[ "$status" != "$prev" ]]; then
        tput cup "$row" 0
        printf "  ${C_BOLD}Prefetch${C_RESET}   %s             " "$status"
        prev="$status"
      fi
      # Stop if completed
      if [[ "$status" == ✓* ]]; then
        break
      fi
      sleep 0.5
    done
  ) &
  _PREFETCH_DISPLAY_PID=$!
}

# Clear screen, print banner, then restrict scrolling to the area below it.
if [[ "$_HAS_TPUT" == "1" ]]; then
  clear
  print_banner
  _start_prefetch_progress
  # Scroll region: from _BANNER_HEIGHT to bottom of screen (0-indexed).
  tput csr "$_BANNER_HEIGHT" $((_ROWS - 1))
  # Place cursor at the top of the scroll region so tail starts there.
  tput cup "$_BANNER_HEIGHT" 0
fi

# ── Stream backend logs in the scroll region ───────────────────────
TAIL_PID=""
if [[ "$_HAS_TPUT" == "1" ]]; then
  tail -n +1 -f "$BACKEND_LOG" 2>/dev/null &
  TAIL_PID=$!
fi

# ── Cleanup on exit ────────────────────────────────────────────────
cleanup() {
  local exit_status="${1:-0}"
  # Remove signal traps so we don't recurse.
  trap - EXIT HUP INT TERM

  # Stop tail first so the terminal stops receiving updates.
  if [[ -n "$TAIL_PID" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true
    wait "$TAIL_PID" 2>/dev/null || true
  fi

  # Stop prefetch progress processes.
  for _pid in "$_PREFETCH_POLL_PID" "$_PREFETCH_DISPLAY_PID"; do
    if [[ -n "$_pid" ]]; then
      kill "$_pid" 2>/dev/null || true
      wait "$_pid" 2>/dev/null || true
    fi
  done
  rm -f "$_PREFETCH_STATUS_FILE"

  # Reset terminal scroll region back to full screen.
  if [[ "$_HAS_TPUT" == "1" ]]; then
    tput csr 0 $((_ROWS - 1))
    clear
  fi

  echo ""
  printf '\e[36m[INFO]\e[0m Shutting down ...\n'

  _cleanup_started_processes

  echo ""
  printf '\e[32m[OK]\e[0m   Droplet stopped\n'
  echo ""
  exit "$exit_status"
}
trap 'cleanup $?' EXIT
trap 'cleanup 129' HUP
trap 'cleanup 130' INT
trap 'cleanup 143' TERM

# ── Wait for backend process ───────────────────────────────────────
wait "$BACKEND_PID"
BACKEND_STATUS=$?

# If we get here the backend exited on its own (e.g. port conflict).
if [[ "$_HAS_TPUT" == "1" && -n "$TAIL_PID" ]]; then
  kill "$TAIL_PID" 2>/dev/null || true
  wait "$TAIL_PID" 2>/dev/null || true
fi
cleanup "$BACKEND_STATUS"
