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

# Helper: return the process group id for a PID, if available
_process_group_id() {
  local pid="$1"
  ps -o pgid= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true
}

# Helper: kill a process and its entire process group (children)
_kill_process_group() {
  local pid="$1"
  local name="$2"
  local pgid
  if [[ -z "$pid" ]]; then return; fi

  if ! kill -0 "$pid" 2>/dev/null; then
    warn "$name PID $pid is not running; removing stale PID file"
    return
  fi

  # Verify the PID is actually a Droplet process (guard against PID reuse)
  if ! _is_droplet_process "$pid"; then
    warn "PID $pid is not a Droplet $name process (possibly reused), skipping"
    return
  fi

  pgid="$(_process_group_id "$pid")"

  # Try killing the whole process group first (works when started with setsid)
  info "Stopping $name process group (PID $pid) ..."
  if [[ -n "$pgid" ]]; then
    kill -- -"$pgid" 2>/dev/null || true
  else
    kill "$pid" 2>/dev/null || true
  fi

  # Wait briefly for graceful shutdown.
  for _ in {1..15}; do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 0.3
  done

  # Force kill if still alive.
  if kill -0 "$pid" 2>/dev/null; then
    warn "$name did not exit gracefully, forcing ..."
    if [[ -n "$pgid" ]]; then
      kill -9 -- -"$pgid" 2>/dev/null || true
    fi
    kill -9 "$pid" 2>/dev/null || true
  fi
  ok "$name stopped"
  STOPPED=1
}

# Helper: check if a PID belongs to a Droplet-related process
_is_droplet_process() {
  local pid="$1"
  local cmdline
  local cwd=""
  # Read command line from /proc (Linux) or ps (macOS fallback)
  if [[ -f "/proc/$pid/cmdline" ]]; then
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
  else
    cmdline=$(ps -p "$pid" -o args= 2>/dev/null || true)
  fi

  # Match only Droplet platform processes. PID files protect us from most
  # ambiguity; cwd checks prevent killing unrelated uvicorn/npm processes.
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

# Helper: find and kill Droplet processes bound to a port (skip non-Droplet)
_kill_by_port() {
  local port="$1"
  local name="$2"
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    for pid in $pids; do
      if _is_droplet_process "$pid"; then
        info "Stopping orphaned $name on port $port (PID $pid)"
        _kill_process_group "$pid" "$name"
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

if [[ "${DROPLET_STOP_BY_PORT:-1}" != "0" ]]; then
  _kill_by_port "$BACKEND_PORT" "backend"
  _kill_by_port "$FRONTEND_PORT" "frontend"
else
  info "port-based Droplet orphan cleanup is disabled by DROPLET_STOP_BY_PORT=0"
fi

# ── Summary ────────────────────────────────────────────────────────
echo ""
if [[ "$STOPPED" == "1" ]]; then
  ok "Droplet platform stopped"
else
  info "No running Droplet processes found"
fi
echo ""
