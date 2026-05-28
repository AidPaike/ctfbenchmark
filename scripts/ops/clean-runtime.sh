#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-}:backend:sdk"
python -m droplet_sdk.cli --timeout "${DROPLET_CLIENT_TIMEOUT:-120}" stop-all || true
python3 -c "import shutil; from pathlib import Path; shutil.rmtree(Path('data/work/challenges'), ignore_errors=True); shutil.rmtree(Path('data/work/attempts'), ignore_errors=True)"
