#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export PYTHONPATH="${PYTHONPATH:-}:${PROJECT_ROOT}/backend:${PROJECT_ROOT}/sdk"
python -m droplet_sdk.cli --timeout "${DROPLET_CLIENT_TIMEOUT:-120}" stop-all || true
python3 - "$PROJECT_ROOT" <<'PY'
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
shutil.rmtree(root / "data" / "work" / "challenges", ignore_errors=True)
shutil.rmtree(root / "data" / "work" / "attempts", ignore_errors=True)
PY
