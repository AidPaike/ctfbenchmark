#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-}:backend:sdk"
python -m droplet_sdk.cli doctor
docker compose version
