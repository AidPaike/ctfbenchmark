from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from droplet import app as app_module
from droplet.events import EventStore
from droplet.models import Challenge


AUTH = {"Authorization": "Bearer droplet_dev_admin"}


def _challenge(template: Path, challenge_id: str = "contract-001") -> Challenge:
    template.mkdir(parents=True, exist_ok=True)
    (template / "docker-compose.yml").write_text(
        """services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
""",
        encoding="utf-8",
    )
    return Challenge(
        id=challenge_id,
        title="Contract Challenge",
        description="A contract-test challenge",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        tags=["contract"],
        hint="try the obvious ID",
        root=str(template),
        compose_path=str(template / "docker-compose.yml"),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
    )


@pytest.fixture()
def api_contract(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DROPLET_PRESTART_CHALLENGES", "0")
    manager = app_module.manager
    old_events = manager.events
    manager.events = EventStore(tmp_path / "events.jsonl")
    challenge = _challenge(tmp_path / "template")

    def fake_load_tasks() -> None:
        manager.challenges = {challenge.id: challenge.model_copy(deep=True)}

    def fake_start_compose(challenge: Challenge, work_dir: Path) -> dict:
        work_dir.mkdir(parents=True, exist_ok=True)
        return {
            "project": f"test_{challenge.id}",
            "work_dir": str(work_dir),
            "target_url": f"http://127.0.0.1/{challenge.id}",
            "ports": [8080],
        }

    monkeypatch.setattr(manager, "load_tasks", fake_load_tasks)
    monkeypatch.setattr(manager, "_start_compose", fake_start_compose)
    monkeypatch.setattr(manager, "_stop_compose", lambda _challenge: None)

    with TestClient(app_module.app) as client:
        yield client, manager

    manager.challenges = {}
    manager.events = old_events


def test_challenges_are_loaded_without_old_runtime_model(api_contract) -> None:
    client, _manager = api_contract

    unauthenticated = client.get("/api/challenges")
    assert unauthenticated.status_code == 401

    response = client.get("/api/challenges", headers=AUTH)
    assert response.status_code == 200
    challenges = response.json()
    assert challenges[0]["id"] == "contract-001"
    assert challenges[0]["status"] == "not_started"
    assert challenges[0]["task_type"] == "web_ctf_online"
    assert "dataset_id" in challenges[0]
    assert "expected_flag" not in challenges[0]


def _wait_for_status(client, expected: str = "running", timeout: float = 2.0) -> dict:
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        challenge = client.get("/api/challenges", headers=AUTH).json()[0]
        if challenge["status"] == expected:
            return challenge
        time.sleep(0.05)
    raise AssertionError(f"Challenge did not reach status {expected}")


def test_start_all_starts_actual_challenge_services(api_contract) -> None:
    client, _manager = api_contract

    response = client.post("/api/challenges/start-all", headers=AUTH, json={})
    assert response.status_code == 200
    assert response.json()["started"] == ["contract-001"]

    challenge = _wait_for_status(client, "running")
    assert challenge["target_url"] == "http://127.0.0.1/contract-001"
    assert challenge["ports"] == [8080]


def test_submit_records_answer_without_reading_or_judging_flag(api_contract) -> None:
    client, _manager = api_contract
    client.post("/api/challenges/contract-001/start", headers=AUTH).raise_for_status()

    challenge = _wait_for_status(client, "running")

    recorded = client.post(
        "/api/challenges/contract-001/submit",
        headers=AUTH,
        json={"answer": "flag{wrong}"},
    )
    assert recorded.status_code == 200
    assert recorded.json()["accepted"] is True
    assert recorded.json()["judged"] is False
    assert recorded.json()["correct"] is None

    challenge = client.get("/api/challenges", headers=AUTH).json()[0]
    assert challenge["status"] == "running"
    assert challenge["solved"] is False
    assert challenge["target_url"] == "http://127.0.0.1/contract-001"
    assert challenge["ports"] == [8080]
    assert challenge["submission_count"] == 1

    stats = client.get("/api/stats", headers=AUTH).json()
    assert stats["total_challenges"] == 1
    assert stats["solved"] == 0
    assert stats["overall_score"] == 0.0


def test_tencent_compat_api_returns_running_ports_and_accepts_answers(api_contract) -> None:
    client, _manager = api_contract
    client.post("/api/challenges/contract-001/start", headers=AUTH).raise_for_status()

    _wait_for_status(client, "running")

    challenges_response = client.get("/api/v1/challenges", headers=AUTH)
    assert challenges_response.status_code == 200
    challenge = challenges_response.json()["challenges"][0]
    assert challenge["challenge_code"] == "contract-001"
    assert challenge["status"] == "running"
    assert challenge["target_url"] == "http://127.0.0.1/contract-001"
    assert challenge["error_message"] is None
    assert challenge["target_info"] == {"ip": "127.0.0.1", "port": [8080]}
    assert challenge["solved"] is False

    rejected = client.post(
        "/api/v1/answer",
        headers=AUTH,
        json={"challenge_code": "contract-001", "answer": "flag{wrong}"},
    )
    assert rejected.status_code == 200
    result = rejected.json()
    assert result == {
        "correct": False,
        "judged": False,
        "accepted": True,
        "earned_points": 0,
        "is_solved": False,
        "message": "submission recorded; no flag judge is configured",
    }


def test_startup_can_prestart_selected_challenges(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DROPLET_PRESTART_CHALLENGES", "1")
    monkeypatch.setenv("DROPLET_PRESTART_IDS", "contract-001")
    manager = app_module.manager
    old_events = manager.events
    manager.events = EventStore(tmp_path / "events.jsonl")
    challenge = _challenge(tmp_path / "template")

    def fake_load_tasks() -> None:
        manager.challenges = {challenge.id: challenge.model_copy(deep=True)}

    def fake_start_compose(challenge: Challenge, work_dir: Path) -> dict:
        return {
            "project": f"test_{challenge.id}",
            "work_dir": str(work_dir),
            "target_url": f"http://127.0.0.1/{challenge.id}",
            "ports": [8080],
        }

    monkeypatch.setattr(manager, "load_tasks", fake_load_tasks)
    monkeypatch.setattr(manager, "_start_compose", fake_start_compose)
    monkeypatch.setattr(manager, "_stop_compose", lambda _challenge: None)

    with TestClient(app_module.app) as client:
        health = client.get("/api/health").json()
        assert health["prestart"]["started"] == ["contract-001"]
        # Prestart is asynchronous; wait briefly for the background thread to finish
        challenge = _wait_for_status(client, "running")
        assert challenge["status"] == "running"

    manager.challenges = {}
    manager.events = old_events


def test_event_api_records_lifecycle_and_accepts_agent_events(api_contract) -> None:
    client, manager = api_contract
    manager.events.clear_memory()

    client.post("/api/challenges/contract-001/start", headers=AUTH).raise_for_status()
    _wait_for_status(client, "running")
    reported = client.post(
        "/api/challenges/contract-001/events",
        headers=AUTH,
        json={"event_type": "agent_event", "message": "curl target", "data": {"tool": "curl"}},
    )
    assert reported.status_code == 200

    events = client.get("/api/challenges/contract-001/events", headers=AUTH).json()
    event_types = [event["event_type"] for event in events]
    assert "challenge_started" in event_types
    assert "agent_event" in event_types
    agent_events = [e for e in events if e["event_type"] == "agent_event"]
    assert len(agent_events) == 1
    assert agent_events[0]["data"] == {"tool": "curl"}

    all_events = client.get("/api/events?challenge_id=contract-001", headers=AUTH).json()
    assert all(event["challenge_id"] == "contract-001" for event in all_events)


def test_event_api_can_clear_activity_without_deleting_rows(api_contract) -> None:
    client, manager = api_contract
    manager.events.clear_memory()

    client.post("/api/challenges/contract-001/start", headers=AUTH).raise_for_status()
    _wait_for_status(client, "running")
    before = client.get("/api/challenges/contract-001/events", headers=AUTH).json()
    assert before

    cleared = client.post("/api/challenges/contract-001/events/clear", headers=AUTH)

    assert cleared.status_code == 200
    assert cleared.json()["cleared"] >= 1
    after = client.get("/api/challenges/contract-001/events", headers=AUTH).json()
    assert after == []
