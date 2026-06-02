#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

info() { printf '\e[36m[ INFO ]\e[0m %s\n' "$*"; }
ok()   { printf '\e[32m[  OK  ]\e[0m %s\n' "$*"; }
warn() { printf '\e[33m[ WARN ]\e[0m %s\n' "$*"; }

_pidfile_backend="${PROJECT_ROOT}/.droplet-backend.pid"
_pidfile_frontend="${PROJECT_ROOT}/.droplet-frontend.pid"

STOPPED=0

# ── Stop backend ───────────────────────────────────────────────────
if [[ -f "$_pidfile_backend" ]]; then
  PID=$(cat "$_pidfile_backend" 2>/dev/null || true)
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    info "Stopping backend (PID $PID) ..."
    kill "$PID" 2>/dev/null || true
    for i in {1..10}; do
      if ! kill -0 "$PID" 2>/dev/null; then break; fi
      sleep 0.5
    done
    if kill -0 "$PID" 2>/dev/null; then
      warn "Backend did not exit gracefully, forcing ..."
      kill -9 "$PID" 2>/dev/null || true
    fi
    ok "Backend stopped"
    STOPPED=1
  else
    warn "Backend PID file exists but process not running"
  fi
  rm -f "$_pidfile_backend"
else
  warn "Backend PID file not found"
fi

# ── Stop frontend ──────────────────────────────────────────────────
if [[ -f "$_pidfile_frontend" ]]; then
  PID=$(cat "$_pidfile_frontend" 2>/dev/null || true)
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    info "Stopping frontend (PID $PID) ..."
    kill "$PID" 2>/dev/null || true
    for i in {1..10}; do
      if ! kill -0 "$PID" 2>/dev/null; then break; fi
      sleep 0.3
    done
    if kill -0 "$PID" 2>/dev/null; then
      warn "Frontend did not exit gracefully, forcing ..."
      kill -9 "$PID" 2>/dev/null || true
    fi
    ok "Frontend stopped"
    STOPPED=1
  else
    warn "Frontend PID file exists but process not running"
  fi
  rm -f "$_pidfile_frontend"
else
  warn "Frontend PID file not found"
fi

# ── Optional port-based cleanup ────────────────────────────────────
if [[ "${STOPPED}" == "0" && "${DROPLET_STOP_BY_PORT:-0}" == "1" ]]; then
  info "Searching for Droplet processes by port ..."
  BACKEND_PORT="${BACKEND_PORT:-1349}"
  FRONTEND_PORT="${FRONTEND_PORT:-10349}"

  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    PID=$(lsof -ti:"$port" 2>/dev/null || ss -tlnp 2>/dev/null | grep ":$port " | sed 's/.*pid=\([0-9]*\).*/\1/' | head -1 || true)
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
      info "Force killing process on port $port (PID $PID)"
      kill -9 "$PID" 2>/dev/null || true
      STOPPED=1
    fi
  done
elif [[ "${STOPPED}" == "0" ]]; then
  warn "No PID file process found; port-based force stop is disabled"
  warn "Set DROPLET_STOP_BY_PORT=1 only when you have verified the port owner is Droplet"
fi

# ── Summary ────────────────────────────────────────────────────────
echo ""
if [[ "$STOPPED" == "1" ]]; then
  ok "Droplet platform stopped"
else
  warn "No running Droplet processes found"
fi
echo ""
