#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Configuration ──────────────────────────────────────────────────
export PYTHONPATH="${PYTHONPATH:-}:${PROJECT_ROOT}/backend:${PROJECT_ROOT}/sdk"
export DROPLET_DATASET_ROOT="${DROPLET_DATASET_ROOT:-${PROJECT_ROOT}/datasets/demo-xbow}"
export DROPLET_WORK_ROOT="${DROPLET_WORK_ROOT:-${PROJECT_ROOT}/data/work}"
export DROPLET_PUBLIC_HOST="${DROPLET_PUBLIC_HOST:-127.0.0.1}"
export DROPLET_DATABASE_PATH="${DROPLET_DATABASE_PATH:-${PROJECT_ROOT}/data/droplet.db}"
export DROPLET_PRESTART_CHALLENGES="${DROPLET_PRESTART_CHALLENGES:-0}"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-1349}"
FRONTEND_PORT="${FRONTEND_PORT:-10349}"

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
info() { printf '\e[36m[INFO]\e[0m %s\n' "$*"; }
ok()   { printf '\e[32m[OK]\e[0m   %s\n' "$*"; }
err()  { printf '\e[31m[ERR]\e[0m  %s\n' "$*" >&2; }

_pidfile_backend="${PROJECT_ROOT}/.droplet-backend.pid"
_pidfile_frontend="${PROJECT_ROOT}/.droplet-frontend.pid"

# ── Stop any existing instances ────────────────────────────────────
bash "${SCRIPT_DIR}/stop.sh" >/dev/null 2>&1 || true

mkdir -p "${PROJECT_ROOT}/logs"

# ── Start frontend in background (if requested) ────────────────────
FRONTEND_PID=""
if [[ "${START_FRONTEND:-1}" == "1" ]]; then
  info "Starting frontend on http://${BACKEND_HOST}:${FRONTEND_PORT} ..."
  cd "${PROJECT_ROOT}/frontend"
  npm run dev >"${PROJECT_ROOT}/logs/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  echo "$FRONTEND_PID" > "$_pidfile_frontend"

  for i in {1..30}; do
    if curl -sf "http://${BACKEND_HOST}:${FRONTEND_PORT}" >/dev/null 2>&1; then
      ok "Frontend ready"
      break
    fi
    sleep 0.5
  done
fi

# ── Trap Ctrl+C to stop frontend ───────────────────────────────────
cleanup() {
  echo ""
  info "Shutting down ..."
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    rm -f "$_pidfile_frontend"
  fi
  rm -f "$_pidfile_backend"
}
trap cleanup EXIT INT TERM

# ── Start backend in foreground ────────────────────────────────────
info "Starting backend on http://${BACKEND_HOST}:${BACKEND_PORT} ..."
info "Dataset: $DROPLET_DATASET_ROOT"
info "Press Ctrl+C to stop"
echo ""

cd "$PROJECT_ROOT"
echo $$ > "$_pidfile_backend"

exec python -m uvicorn droplet.app:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT"
