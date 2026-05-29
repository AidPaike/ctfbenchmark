from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

if os.getenv("DROPLET_RUN_DOCKER_E2E") != "1":
    pytest.skip(
        "set DROPLET_RUN_DOCKER_E2E=1 to run the real Docker/API challenge smoke test",
        allow_module_level=True,
    )


AUTH_HEADERS = {"Authorization": "Bearer droplet_dev_admin"}
DATASET_ROOT = Path(os.getenv("DROPLET_E2E_DATASET_ROOT", "datasets/demo-xbow"))
DEFAULT_TASK_ID = "xben-001-24"
SERVER_READY_TIMEOUT_SECONDS = int(os.getenv("DROPLET_E2E_SERVER_TIMEOUT", "30"))
TARGET_READY_TIMEOUT_SECONDS = int(os.getenv("DROPLET_E2E_READY_TIMEOUT", "300"))


@pytest.fixture()
def droplet_server(tmp_path: Path):
    port = _free_port()
    work_root = tmp_path / "work"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{Path.cwd() / 'backend'}:{Path.cwd() / 'sdk'}:{env.get('PYTHONPATH', '')}"
    env["DROPLET_WORK_ROOT"] = str(work_root)
    env["DROPLET_DATASET_ROOT"] = str(DATASET_ROOT)
    env["DROPLET_PUBLIC_HOST"] = "127.0.0.1"
    env["DROPLET_PRESTART_CHALLENGES"] = "0"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "droplet.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url, process)
        yield base_url, work_root
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_api_can_start_challenge_record_submission_and_cleanup(droplet_server) -> None:
    base_url, work_root = droplet_server
    task_id = os.getenv("DROPLET_E2E_TASK_ID", DEFAULT_TASK_ID)

    with httpx.Client(base_url=base_url, headers=AUTH_HEADERS, timeout=600.0, trust_env=False) as client:
        challenges = _ok(client.get("/api/challenges"))
        assert any(challenge["id"] == task_id for challenge in challenges)

        start_resp = client.post(f"/api/challenges/{task_id}/start")
        assert start_resp.status_code == 202, start_resp.text
        challenge = start_resp.json()
        assert challenge["status"] == "starting"

        # Poll until the background start finishes
        deadline = time.monotonic() + TARGET_READY_TIMEOUT_SECONDS
        last_status = challenge["status"]
        while time.monotonic() < deadline:
            challenge = _ok(client.get(f"/api/challenges/{task_id}"))
            last_status = challenge["status"]
            if last_status in ("running", "error"):
                break
            time.sleep(2)
        assert last_status == "running", f"Challenge did not reach running state, final status: {last_status}"

        endpoint = challenge["target_url"]
        assert endpoint
        _wait_for_target(endpoint)

        recorded = _ok(
            client.post(
                f"/api/challenges/{task_id}/submit",
                json={"answer": "flag{agent_found}"},
            )
        )
        assert recorded["accepted"] is True
        assert recorded["judged"] is False
        assert recorded["correct"] is None

        stats = _ok(client.get("/api/stats"))
        assert stats["solved"] == 0
        assert stats["overall_score"] == 0.0

        challenge_after = next(item for item in _ok(client.get("/api/challenges")) if item["id"] == task_id)
        assert challenge_after["status"] == "running"
        assert challenge_after["submission_count"] == 1

        stop_response = client.post(f"/api/challenges/{task_id}/stop")
        assert stop_response.status_code == 202, stop_response.text
        stopped = _wait_for_challenge_status(client, task_id, {"not_started", "error"})
        assert stopped["status"] == "not_started"

    work_dir = work_root / "challenges" / task_id
    for _ in range(20):
        if not work_dir.exists():
            break
        time.sleep(0.5)
    assert not work_dir.exists()


def _ok(response: httpx.Response) -> Any:
    assert response.status_code < 400, response.text
    return response.json()


def _wait_for_server(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + SERVER_READY_TIMEOUT_SECONDS
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"Droplet server exited early with {process.returncode}:\n{output}")
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=1.0, trust_env=False)
            if response.status_code == 200:
                return
            last_error = response.text
        except Exception as exc:  # pragma: no cover - diagnostic detail for real server runs
            last_error = str(exc)
        time.sleep(0.5)
    raise AssertionError(f"Droplet server did not become ready at {base_url}: {last_error}")


def _wait_for_target(base_url: str) -> None:
    deadline = time.monotonic() + TARGET_READY_TIMEOUT_SECONDS
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(base_url, timeout=3.0, follow_redirects=True, trust_env=False)
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:  # pragma: no cover - diagnostic detail for real Docker runs
            last_error = str(exc)
        time.sleep(2)
    raise AssertionError(f"target did not become ready at {base_url}: {last_error}")


def _wait_for_challenge_status(
    client: httpx.Client,
    challenge_id: str,
    statuses: set[str],
) -> dict[str, Any]:
    deadline = time.monotonic() + TARGET_READY_TIMEOUT_SECONDS
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = _ok(client.get(f"/api/challenges/{challenge_id}"))
        if last["status"] in statuses:
            return last
        time.sleep(2)
    raise AssertionError(f"Challenge {challenge_id} did not reach {statuses}; last={last}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
