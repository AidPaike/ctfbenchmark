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

# Helper: kill a process and its entire process group (children)
_kill_process_group() {
  local pid="$1"
  local name="$2"
  if [[ -z "$pid" ]]; then return; fi

  # Verify the PID is actually a Droplet process (guard against PID reuse)
  if ! _is_droplet_process "$pid"; then
    warn "PID $pid is not a Droplet $name process (possibly reused), skipping"
    return
  fi

  # Try killing the whole process group first (works when started with setsid)
  if kill -0 "$pid" 2>/dev/null; then
    info "Stopping $name process group (PID $pid) ..."
    kill -- -"$pid" 2>/dev/null || true
    # Wait briefly for graceful shutdown
    for _ in {1..10}; do
      if ! kill -0 "$pid" 2>/dev/null; then break; fi
      sleep 0.3
    done
    # Force kill if still alive
    if kill -0 "$pid" 2>/dev/null; then
      warn "$name did not exit gracefully, forcing ..."
      kill -9 -- -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
    fi
    ok "$name stopped"
    STOPPED=1
  fi
}

# Helper: check if a PID belongs to a Droplet-related process
_is_droplet_process() {
  local pid="$1"
  local cmdline
  # Read command line from /proc (Linux) or ps (macOS fallback)
  if [[ -f "/proc/$pid/cmdline" ]]; then
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
  else
    cmdline=$(ps -p "$pid" -o args= 2>/dev/null || true)
  fi
  # Match Droplet-related keywords: uvicorn, droplet, npm run dev (in project dir)
  if [[ "$cmdline" == *"uvicorn"*"droplet"* ]] || \
     [[ "$cmdline" == *"droplet"* ]] || \
     [[ "$cmdline" == *"npm"*"run"*"dev"* && "$cmdline" == *"frontend"* ]]; then
    return 0
  fi
  return 1
}

# Helper: find and kill Droplet processes bound to a port (skip non-Droplet)
_kill_by_port() {
  local port="$1"
  local name="$2"
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    for pid in $pids; do
      if _is_droplet_process "$pid"; then
        info "Killing $name on port $port (PID $pid)"
        kill -9 "$pid" 2>/dev/null || true
        STOPPED=1
      else
        warn "Port $port occupied by non-Droplet process (PID $pid), skipping"
      fi
    done
  fi
}

# ── Stop backend ───────────────────────────────────────────────────
if [[ -f "$_pidfile_backend" ]]; then
  PID=$(cat "$_pidfile_backend" 2>/dev/null || true)
  if [[ -n "$PID" ]]; then
    _kill_process_group "$PID" "backend"
  else
    warn "Backend PID file is empty"
  fi
  rm -f "$_pidfile_backend"
else
  info "Backend PID file not found"
fi

# ── Stop frontend ──────────────────────────────────────────────────
if [[ -f "$_pidfile_frontend" ]]; then
  PID=$(cat "$_pidfile_frontend" 2>/dev/null || true)
  if [[ -n "$PID" ]]; then
    _kill_process_group "$PID" "frontend"
  else
    warn "Frontend PID file is empty"
  fi
  rm -f "$_pidfile_frontend"
else
  info "Frontend PID file not found"
fi

# ── Port-based cleanup (always runs) ──────────────────────────────
BACKEND_PORT="${BACKEND_PORT:-1349}"
FRONTEND_PORT="${FRONTEND_PORT:-10349}"

_kill_by_port "$BACKEND_PORT" "backend"
_kill_by_port "$FRONTEND_PORT" "frontend"

# ── Summary ────────────────────────────────────────────────────────
echo ""
if [[ "$STOPPED" == "1" ]]; then
  ok "Droplet platform stopped"
else
  info "No running Droplet processes found"
fi
echo ""
