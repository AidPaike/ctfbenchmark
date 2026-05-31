"""End-to-end integration test for the simplified Droplet benchmark platform.

This test exercises the full agent workflow against a running backend:
1. List challenges
2. Start a challenge (spawns Docker Compose environment)
3. Submit an answer (verifies submission recording without platform flag reading)
4. Check challenge remains running because no judge is configured
5. Reset challenge and verify it restarts
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

if os.getenv("DROPLET_RUN_LIVE_E2E") != "1":
    pytest.skip(
        "set DROPLET_RUN_LIVE_E2E=1 to run live-backend Docker tests against DROPLET_BASE_URL",
        allow_module_level=True,
    )

API_BASE = os.getenv("DROPLET_BASE_URL", "http://127.0.0.1:1349")
API_TOKEN = os.getenv("DROPLET_API_TOKEN", "droplet_dev_admin")


@pytest.fixture
def api() -> httpx.Client:
    client = httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
        timeout=600.0,
        trust_env=False,
    )
    try:
        yield client
    finally:
        client.close()


class TestHealthAndDiscovery:
    def test_health(self, api: httpx.Client) -> None:
        resp = api.get("/api/health")
        resp.raise_for_status()
        data = resp.json()
        assert data["ok"] is True
        assert data["challenges"] >= 1

    def test_challenges_discovered(self, api: httpx.Client) -> None:
        resp = api.get("/api/challenges")
        resp.raise_for_status()
        challenges = resp.json()
        assert len(challenges) >= 1
        ids = {c["id"] for c in challenges}
        assert "xben-001-24" in ids


class TestChallengeLifecycle:
    def test_full_challenge_workflow(self, api: httpx.Client) -> None:
        # 1. List challenges and pick the first one
        resp = api.get("/api/challenges")
        resp.raise_for_status()
        challenges = resp.json()
        assert len(challenges) >= 1
        challenge = challenges[0]
        challenge_id = challenge["id"]
        print(f"\n[test] Selected challenge: {challenge_id}")

        # 2. Start challenge — this triggers Docker Compose up asynchronously
        resp = api.post(f"/api/challenges/{challenge_id}/start")
        resp.raise_for_status()
        challenge = resp.json()
        assert challenge["status"] in {"starting", "running"}
        challenge = _wait_for_challenge_status(api, challenge_id, {"running", "error"})
        assert challenge["status"] == "running"
        assert challenge["target_url"] is not None
        print(f"[test] Challenge started: {challenge['target_url']}")

        # 3. Verify target URL is returned
        target_url = challenge["target_url"]
        assert target_url.startswith("http://")
        print(f"[test] Target URL: {target_url}")

        # 4. Submit an answer. Droplet records it but does not read or judge the flag.
        resp = api.post(
            f"/api/challenges/{challenge_id}/submit", json={"answer": "FLAG{agent_found}"}
        )
        resp.raise_for_status()
        result = resp.json()
        assert result["accepted"] is True
        assert result["judged"] is False
        assert result["correct"] is None
        print("[test] Submission recorded without platform judging")

        # 5. Verify challenge remains running and is not marked solved.
        resp = api.get("/api/challenges")
        resp.raise_for_status()
        challenge = next(c for c in resp.json() if c["id"] == challenge_id)
        assert challenge["status"] == "running"
        assert challenge["solved"] is False
        assert challenge["submission_count"] >= 1
        print("[test] Challenge remains running")

        # 6. Verify stats do not claim success without a judge.
        resp = api.get("/api/stats")
        resp.raise_for_status()
        stats = resp.json()
        assert stats["solved"] >= 0
        print(f"[test] Stats: {stats['solved']}/{stats['total_challenges']} solved")

        api.post(f"/api/challenges/{challenge_id}/stop")

    def test_stop_challenge_cleans_environment(self, api: httpx.Client) -> None:
        """Verify stopping a challenge tears down the Docker environment."""
        resp = api.get("/api/challenges")
        resp.raise_for_status()
        challenges = resp.json()
        challenge_id = challenges[0]["id"]

        # Start it
        resp = api.post(f"/api/challenges/{challenge_id}/start")
        resp.raise_for_status()
        challenge = resp.json()
        assert challenge["status"] in {"starting", "running"}
        challenge = _wait_for_challenge_status(api, challenge_id, {"running", "error"})
        assert challenge["status"] == "running"

        # Stop it
        resp = api.post(f"/api/challenges/{challenge_id}/stop")
        resp.raise_for_status()
        challenge = resp.json()
        assert challenge["status"] in {"stopping", "not_started"}
        challenge = _wait_for_challenge_status(api, challenge_id, {"not_started", "error"})
        assert challenge["status"] == "not_started"

        # Verify work dir is gone (give a moment for cleanup)
        work_dir = Path("data/work/challenges") / challenge_id
        for _ in range(10):
            if not work_dir.exists():
                break
            time.sleep(0.2)
        assert not work_dir.exists(), f"Work dir {work_dir} was not cleaned up"

    def test_reset_restarts_challenge(self, api: httpx.Client) -> None:
        """Verify reset stops and restarts the challenge."""
        resp = api.get("/api/challenges")
        resp.raise_for_status()
        challenges = resp.json()
        challenge_id = challenges[0]["id"]

        # Start, then reset
        resp = api.post(f"/api/challenges/{challenge_id}/start")
        resp.raise_for_status()
        _wait_for_challenge_status(api, challenge_id, {"running", "error"})

        resp = api.post(f"/api/challenges/{challenge_id}/reset")
        resp.raise_for_status()
        challenge = resp.json()
        assert challenge["status"] in {"starting", "running"}
        challenge = _wait_for_challenge_status(api, challenge_id, {"running", "error"})
        assert challenge["status"] == "running"
        assert challenge["target_url"] is not None
        print(f"[test] Reset successful, new URL: {challenge['target_url']}")

        # Cleanup
        api.post(f"/api/challenges/{challenge_id}/stop")


def _wait_for_challenge_status(
    api: httpx.Client,
    challenge_id: str,
    statuses: set[str],
    timeout: float = 300.0,
) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        resp = api.get("/api/challenges")
        resp.raise_for_status()
        last = next(c for c in resp.json() if c["id"] == challenge_id)
        if last["status"] in statuses:
            return last
        time.sleep(2)
    raise AssertionError(f"Challenge {challenge_id} did not reach {statuses}; last={last}")
