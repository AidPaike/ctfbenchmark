from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_ci_runs_non_docker_api_contract_tests() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "tests/integration/test_api_contract.py" in workflow


def test_platform_scripts_only_kill_verified_droplet_port_processes() -> None:
    start_script = _read("scripts/platform/start.sh")
    stop_script = _read("scripts/platform/stop.sh")

    assert "DROPLET_FORCE_KILL_PORTS" in start_script
    assert "DROPLET_STOP_BY_PORT" in stop_script
    assert "Port $port is already in use" in start_script
    assert "_is_droplet_process" in stop_script
    assert "Port $port occupied by non-Droplet process" in stop_script
    assert "DROPLET_STOP_BY_PORT:-1" in stop_script


def test_prefetch_progress_uses_configured_api_token() -> None:
    start_script = _read("scripts/platform/start.sh")
    show_script = _read("scripts/ops/show-prefetch-progress.sh")

    assert '"$DROPLET_API_TOKEN"' in start_script
    assert 'TOKEN="${2:-${DROPLET_API_TOKEN:-droplet_dev_admin}}"' in show_script


def test_env_example_documents_only_supported_runtime_variables() -> None:
    env_example = _read(".env.example")
    documented = set(re.findall(r"^(DROPLET_[A-Z0-9_]+)=", env_example, flags=re.MULTILINE))
    unsupported = {"DROPLET_PREFETCH_WORKERS", "DROPLET_FORCE_REBUILD"}

    assert unsupported.isdisjoint(documented)
    assert {
        "DROPLET_API_TOKEN",
        "DROPLET_PRESTART_CHALLENGES",
        "DROPLET_PREFETCH_IMAGES",
        "DROPLET_SHOW_SUBMISSION_ANSWERS",
    }.issubset(documented)
