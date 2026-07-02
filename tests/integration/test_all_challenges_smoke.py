"""Smoke test: start every challenge one-by-one and verify it reaches 'running'.

Requires Docker.  Gate with env var:

    DROPLET_RUN_ALL_CHALLENGES=1 pytest tests/integration/test_all_challenges_smoke.py -v -s

Optional env vars:
    DROPLET_E2E_DATASET_ROOT  — dataset directory (default: datasets)
    DROPLET_E2E_SERVER_TIMEOUT — seconds to wait for the backend to start (default: 60)
    DROPLET_E2E_READY_TIMEOUT  — seconds to wait for a challenge to become ready (default: 300)
    DROPLET_E2E_FILTER         — only test challenges whose id contains this substring
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from urllib.parse import urlparse
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.helpers import auth_headers

if os.getenv("DROPLET_RUN_ALL_CHALLENGES") != "1":
    pytest.skip(
        "set DROPLET_RUN_ALL_CHALLENGES=1 to run the all-challenges smoke test",
        allow_module_level=True,
    )

AUTH_HEADERS = auth_headers(os.getenv("DROPLET_API_TOKEN", "droplet_dev_admin"))
DATASET_ROOT = Path(os.getenv("DROPLET_E2E_DATASET_ROOT", "datasets"))
SERVER_READY_TIMEOUT = int(os.getenv("DROPLET_E2E_SERVER_TIMEOUT", "60"))
CHALLENGE_READY_TIMEOUT = int(os.getenv("DROPLET_E2E_READY_TIMEOUT", "300"))
CHALLENGE_FILTER = os.getenv("DROPLET_E2E_FILTER", "")


def _log(msg: str) -> None:
    """Print with flush so output appears immediately in pytest -s."""
    print(msg, flush=True)


@pytest.fixture(scope="module")
def droplet_server(tmp_path_factory: pytest.TempPathFactory):
    """Start a Droplet backend once for the entire module."""
    tmp = tmp_path_factory.mktemp("droplet_all")
    work_root = tmp / "work"
    log_file = tmp / "server.log"
    port = _free_port()

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{Path.cwd() / 'backend'}:{Path.cwd() / 'sdk'}:{env.get('PYTHONPATH', '')}"
    env["DROPLET_WORK_ROOT"] = str(work_root)
    env["DROPLET_DATASET_ROOT"] = str(DATASET_ROOT)
    env["DROPLET_PUBLIC_HOST"] = "127.0.0.1"
    env["DROPLET_PRESTART_CHALLENGES"] = "0"
    env["DROPLET_PREFETCH_IMAGES"] = "0"
    env["DROPLET_TARGET_READY_TIMEOUT"] = "600"
    env["DROPLET_COMPOSE_TIMEOUT_SECONDS"] = "900"

    _log(f"\n{'=' * 60}")
    _log(f"[server] Starting Droplet backend on port {port}")
    _log(f"[server] DATASET_ROOT={DATASET_ROOT}")
    _log(f"[server] WORK_ROOT={work_root}")
    _log(f"[server] LOG_FILE={log_file}")
    _log(f"{'=' * 60}")

    log_fh = log_file.open("w")
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
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _log(f"[server] PID={process.pid}")

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url, process, log_file)
        _log(f"[server] Ready at {base_url}")
        yield base_url, work_root
    finally:
        _log("[server] Shutting down...")
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _log("[server] Force killing...")
            process.kill()
            process.wait(timeout=10)
        log_fh.close()
        # Dump server log for debugging
        if log_file.exists():
            log_text = log_file.read_text()
            if log_text.strip():
                _log(f"\n[server log]\n{log_text[-3000:]}")
            log_file.unlink(missing_ok=True)
        _log("[server] Stopped")


@pytest.fixture(scope="module")
def all_challenge_ids(droplet_server) -> list[str]:
    """Fetch the full challenge list from the backend."""
    base_url, _ = droplet_server
    _log("[fixture] Fetching challenge list...")
    with httpx.Client(base_url=base_url, headers=AUTH_HEADERS, timeout=30.0, trust_env=False) as c:
        challenges = _ok(c.get("/api/challenges"))
    ids = [ch["id"] for ch in challenges]
    if CHALLENGE_FILTER:
        ids = [i for i in ids if CHALLENGE_FILTER in i]
    _log(
        f"[fixture] Found {len(ids)} challenges"
        + (f" (filter={CHALLENGE_FILTER!r})" if CHALLENGE_FILTER else "")
    )
    assert ids, f"No challenges found (filter={CHALLENGE_FILTER!r})"
    return sorted(ids)


def test_all_challenges_start_and_stop(
    droplet_server: tuple[str, Path],
    all_challenge_ids: list[str],
) -> None:
    """Start each challenge, verify it reaches 'running', then stop it."""
    base_url, work_root = droplet_server
    total = len(all_challenge_ids)
    results: list[dict[str, Any]] = []

    _log(f"\n{'=' * 60}")
    _log(f"SMOKE TEST: {total} challenges to test")
    _log(f"{'=' * 60}")

    with httpx.Client(
        base_url=base_url, headers=AUTH_HEADERS, timeout=600.0, trust_env=False
    ) as client:
        for idx, cid in enumerate(all_challenge_ids, 1):
            _log(f"\n{'─' * 60}")
            _log(f"[{idx}/{total}] {cid}")
            _log(f"{'─' * 60}")

            record: dict[str, Any] = {"id": cid, "status": "unknown", "error": None}
            try:
                # ── Start ──
                _log(f"  [→] POST /api/challenges/{cid}/start")
                t0 = time.monotonic()
                start_resp = client.post(f"/api/challenges/{cid}/start")
                _log(f"  [→] Response {start_resp.status_code}: {start_resp.text[:200]}")
                assert start_resp.status_code in (200, 202), (
                    f"Start returned {start_resp.status_code}: {start_resp.text}"
                )
                challenge = start_resp.json()
                assert challenge["status"] in ("starting", "running"), (
                    f"Unexpected status after start: {challenge['status']}"
                )

                # ── Wait for running ──
                _log(f"  [⏳] Waiting for 'running' (timeout={CHALLENGE_READY_TIMEOUT}s)...")
                challenge = _wait_for_challenge_status(
                    client, cid, {"running", "error"}, CHALLENGE_READY_TIMEOUT
                )
                elapsed = time.monotonic() - t0
                _log(f"  [⏳] Status={challenge['status']} after {elapsed:.1f}s")

                assert challenge["status"] == "running", (
                    f"Challenge {cid} ended in status '{challenge['status']}': "
                    f"{challenge.get('error_message', 'no error message')}"
                )
                record["status"] = "running"

                # ── Verify target URL ──
                target_url = challenge.get("target_url")
                assert target_url, f"Challenge {cid} has no target_url"
                record["target_url"] = target_url
                _log(f"  [🌐] Target: {target_url}")
                _log("  [🌐] Checking target reachability...")
                _wait_for_target(target_url, timeout=60)
                record["target_reachable"] = True
                _log(f"  [✓] PASSED — {cid} running at {target_url} ({elapsed:.1f}s)")

            except Exception as exc:
                record["status"] = "error"
                record["error"] = str(exc)
                _log(f"  [✗] FAILED — {cid}: {exc}")

            finally:
                # ── Stop ──
                try:
                    _log(f"  [←] POST /api/challenges/{cid}/stop")
                    stop_resp = client.post(f"/api/challenges/{cid}/stop")
                    _log(f"  [←] Response {stop_resp.status_code}")
                    _log("  [⏳] Waiting for 'not_started'...")
                    _wait_for_challenge_status(client, cid, {"not_started", "error"}, timeout=120)
                    _log("  [←] Stopped")
                except Exception as cleanup_exc:
                    _log(f"  [!] Cleanup failed: {cleanup_exc}")
                    record["cleanup_error"] = str(cleanup_exc)

                # Wait for work dir cleanup
                work_dir = work_root / "challenges" / cid
                for _ in range(20):
                    if not work_dir.exists():
                        break
                    time.sleep(0.5)

            results.append(record)

    # ── Summary ──────────────────────────────────────────────────────
    passed = [r for r in results if r["status"] == "running"]
    failed = [r for r in results if r["status"] != "running"]

    _log(f"\n{'=' * 60}")
    _log(f"SUMMARY: {len(passed)}/{len(results)} passed")
    _log(f"{'=' * 60}")

    if failed:
        _log("\nFailed:")
        for r in failed:
            _log(f"  ✗ {r['id']}: {r['error']}")

    # Write results to JSON for post-mortem analysis
    results_file = Path("smoke_test_results.json")
    results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    _log(f"\n[results] Saved to {results_file.resolve()}")

    assert not failed, f"{len(failed)}/{len(results)} challenges failed to start:\n" + "\n".join(
        f"  - {r['id']}: {r['error']}" for r in failed
    )


# ── Helpers ─────────────────────────────────────────────────────────────


def _ok(response: httpx.Response) -> Any:
    assert response.status_code < 400, f"HTTP {response.status_code}: {response.text[:500]}"
    return response.json()


def _wait_for_server(
    base_url: str, process: subprocess.Popen[str], log_path: Path | None = None
) -> None:
    deadline = time.monotonic() + SERVER_READY_TIMEOUT
    last_error = ""
    attempt = 0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = ""
            if log_path and log_path.exists():
                output = log_path.read_text()
            raise AssertionError(
                f"Droplet server exited early with {process.returncode}:\n{output[-2000:]}"
            )
        attempt += 1
        try:
            resp = httpx.get(f"{base_url}/api/health", timeout=1.0, trust_env=False)
            if resp.status_code == 200:
                data = resp.json()
                _log(f"[server] Health OK after {attempt} attempts — {data}")
                return
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if attempt % 10 == 0:
                _log(f"[server] Still waiting... attempt={attempt}, last_error={last_error}")
        except Exception as exc:
            last_error = str(exc)
            if attempt % 10 == 0:
                _log(f"[server] Still waiting... attempt={attempt}, error={last_error}")
        time.sleep(0.5)
    # Final dump
    if log_path and log_path.exists():
        log_text = log_path.read_text()
        _log(f"[server log on timeout]\n{log_text[-2000:]}")
    raise AssertionError(
        f"Server not ready at {base_url} after {SERVER_READY_TIMEOUT}s: {last_error}"
    )


def _wait_for_challenge_status(
    client: httpx.Client,
    challenge_id: str,
    statuses: set[str],
    timeout: float = CHALLENGE_READY_TIMEOUT,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    poll_count = 0
    while time.monotonic() < deadline:
        last = _ok(client.get(f"/api/challenges/{challenge_id}"))
        poll_count += 1
        if last["status"] in statuses:
            return last
        if poll_count % 15 == 0:
            elapsed = timeout - (deadline - time.monotonic())
            _log(f"    ... still {last['status']} after {elapsed:.0f}s (poll #{poll_count})")
        time.sleep(2)
    raise AssertionError(
        f"Challenge {challenge_id} did not reach {statuses} within {timeout}s; last={last}"
    )


def _wait_for_target(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    attempt = 0

    # Parse protocol and endpoint
    if url.startswith("tcp://"):
        # TCP service — use socket connect
        _wait_for_tcp(url, timeout)
        return

    # HTTP/HTTPS service — use httpx, don't follow redirects
    # (some services like WordPress redirect to a different host/port,
    # which would cause a spurious connection refused)
    while time.monotonic() < deadline:
        attempt += 1
        try:
            resp = httpx.get(url, timeout=3.0, follow_redirects=False, trust_env=False)
            if resp.status_code < 500:
                _log(f"    target reachable after {attempt} attempt(s)")
                return
            last_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_error = str(exc)
        if attempt % 5 == 0:
            _log(f"    target not ready yet... attempt={attempt}, error={last_error}")
        time.sleep(2)
    raise AssertionError(f"Target not reachable at {url} after {timeout}s: {last_error}")


def _wait_for_tcp(url: str, timeout: float = 60) -> None:
    """Check TCP port reachability using socket connect."""
    # tcp://host:port → (host, port)
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    assert port, f"TCP URL has no port: {url}"

    deadline = time.monotonic() + timeout
    last_error = ""
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(3.0)
                result = sock.connect_ex((host, port))
                if result == 0:
                    _log(f"    TCP target reachable after {attempt} attempt(s)")
                    return
                last_error = f"connect_ex={result}"
        except Exception as exc:
            last_error = str(exc)
        if attempt % 5 == 0:
            _log(f"    TCP target not ready yet... attempt={attempt}, error={last_error}")
        time.sleep(2)
    raise AssertionError(f"TCP target not reachable at {url} after {timeout}s: {last_error}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
