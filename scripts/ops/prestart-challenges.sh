#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export PYTHONPATH="${PYTHONPATH:-}:${PROJECT_ROOT}/backend:${PROJECT_ROOT}/sdk"
python -m droplet_sdk.cli --timeout "${DROPLET_CLIENT_TIMEOUT:-600}" preflight "$@"
