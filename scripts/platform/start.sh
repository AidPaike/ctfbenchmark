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

# ── Stop any existing instances ────────────────────────────────────
bash "${SCRIPT_DIR}/stop.sh" >/dev/null 2>&1 || true

mkdir -p "$LOG_DIR"
rm -f "$BACKEND_LOG"

# ── Start frontend in background ───────────────────────────────────
FRONTEND_PID=""
if [[ "${START_FRONTEND:-1}" == "1" ]]; then
  cd "${PROJECT_ROOT}/frontend"
  npm run dev >"${LOG_DIR}/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  echo "$FRONTEND_PID" > "$_pidfile_frontend"
fi

# ── Start backend in background ────────────────────────────────────
cd "$PROJECT_ROOT"
echo $$ > "$_pidfile_backend"

python -m uvicorn droplet.app:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

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
  echo -e "  ${C_DIM}Press Ctrl+C to stop${C_RESET}"
  echo ""
}

# Clear screen, print banner, then restrict scrolling to the area below it.
if [[ "$_HAS_TPUT" == "1" ]]; then
  clear
  print_banner
  # Scroll region: from _BANNER_HEIGHT to bottom of screen (0-indexed).
  tput csr "$_BANNER_HEIGHT" $((_ROWS - 1))
  # Place cursor at the top of the scroll region so tail starts there.
  tput cup "$_BANNER_HEIGHT" 0
fi

# ── Stream backend logs in the scroll region ───────────────────────
TAIL_PID=""
if [[ "$_HAS_TPUT" == "1" ]]; then
  tail -n +1 -f "$BACKEND_LOG" &
  TAIL_PID=$!
fi

# ── Cleanup on exit ────────────────────────────────────────────────
cleanup() {
  # Remove signal traps so we don't recurse.
  trap - EXIT INT TERM

  # Stop tail first so the terminal stops receiving updates.
  if [[ -n "$TAIL_PID" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true
    wait "$TAIL_PID" 2>/dev/null || true
  fi

  # Reset terminal scroll region back to full screen.
  if [[ "$_HAS_TPUT" == "1" ]]; then
    tput csr 0 $((_ROWS - 1))
    clear
  fi

  echo ""
  printf '\e[36m[INFO]\e[0m Shutting down ...\n'

  if kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi

  rm -f "$_pidfile_frontend" "$_pidfile_backend"

  echo ""
  printf '\e[32m[OK]\e[0m   Droplet stopped\n'
  echo ""
  exit 0
}
trap 'cleanup' INT TERM

# ── Wait for backend process ───────────────────────────────────────
wait "$BACKEND_PID"

# If we get here the backend exited on its own (e.g. port conflict).
if [[ "$_HAS_TPUT" == "1" && -n "$TAIL_PID" ]]; then
  kill "$TAIL_PID" 2>/dev/null || true
  wait "$TAIL_PID" 2>/dev/null || true
fi
cleanup
