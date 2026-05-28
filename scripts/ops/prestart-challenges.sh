#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-}:backend:sdk"
python -m droplet_sdk.cli --timeout "${DROPLET_CLIENT_TIMEOUT:-600}" preflight "$@"
