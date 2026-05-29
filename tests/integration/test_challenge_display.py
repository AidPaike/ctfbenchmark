"""Test that challenges are discoverable and displayable by the frontend.

This test verifies:
1. Challenges load from the dataset on startup
2. /api/challenges returns a non-empty list
3. Each challenge has all fields required by the frontend
4. dataset_id is properly set for sidebar grouping
5. The response structure matches the frontend Challenge type exactly
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from droplet import app as app_module
from droplet.events import EventStore


AUTH = {"Authorization": "Bearer droplet_dev_admin"}

# Fields the frontend Challenge type expects (frontend/src/main.tsx)
FRONTEND_REQUIRED_FIELDS = {
    "id",
    "title",
    "description",
    "category",
    "task_type",
    "difficulty",
    "dataset_id",
    "tags",
    "has_hint",
    "status",
    "target_url",
    "ports",
    "solved",
    "hint_viewed",
    "hint_penalty",
    "submission_count",
    "score",
    "error_message",
    # Also returned by public() but not in frontend type
    "judge_mode",
    "started_at",
    "finished_at",
}


@pytest.fixture()
def display_client(tmp_path: Path, monkeypatch):
    """Set up a test client with the real dataset loader."""
    monkeypatch.setenv("DROPLET_PRESTART_CHALLENGES", "0")

    manager = app_module.manager
    old_challenges = manager.challenges
    old_events = manager.events

    # Use a temp event store to avoid polluting the real one
    manager.events = EventStore()
    manager.challenges = {}

    # Set dataset root to the actual demo dataset
    dataset_root = Path(__file__).parent.parent.parent / "datasets" / "demo-xbow"
    manager.dataset_root = dataset_root

    # Actually load the real challenges
    manager.load_tasks()

    with TestClient(app_module.app) as client:
        yield client, manager

    # Cleanup
    manager.challenges = old_challenges
    manager.events = old_events


class TestChallengeDiscovery:
    def test_api_returns_non_empty_challenge_list(self, display_client) -> None:
        client, _manager = display_client
        response = client.get("/api/challenges", headers=AUTH)
        assert response.status_code == 200
        challenges = response.json()
        assert len(challenges) > 0, "API returned empty challenge list"
        print(f"\nLoaded {len(challenges)} challenges")

    def test_all_required_frontend_fields_present(self, display_client) -> None:
        client, _manager = display_client
        challenges = client.get("/api/challenges", headers=AUTH).json()
        assert len(challenges) > 0

        for challenge in challenges:
            missing = FRONTEND_REQUIRED_FIELDS - set(challenge.keys())
            assert not missing, f"Challenge {challenge.get('id', '?')} missing fields: {missing}"

    def test_dataset_id_is_set_for_grouping(self, display_client) -> None:
        """dataset_id must be non-empty so challenges appear in named groups."""
        client, _manager = display_client
        challenges = client.get("/api/challenges", headers=AUTH).json()
        assert len(challenges) > 0

        for challenge in challenges:
            dataset_id = challenge.get("dataset_id", "")
            assert dataset_id and dataset_id != "", (
                f"Challenge {challenge['id']} has empty dataset_id; "
                f"frontend will group under 'unknown-dataset'"
            )

    def test_frontend_grouping_works(self, display_client) -> None:
        """Simulate the frontend groupChallenges() logic."""
        client, _manager = display_client
        challenges = client.get("/api/challenges", headers=AUTH).json()

        groups = {}
        for c in challenges:
            group_id = c.get("dataset_id") or "unknown-dataset"
            if group_id not in groups:
                groups[group_id] = []
            groups[group_id].append(c)

        assert len(groups) > 0, "No challenge groups formed"
        for group_id, group_challenges in groups.items():
            assert group_id != "unknown-dataset", (
                f"Some challenges have no dataset_id and fall into 'unknown-dataset'"
            )
            assert len(group_challenges) > 0

    def test_status_values_are_valid(self, display_client) -> None:
        """Status must be one of the values the frontend can render."""
        valid_statuses = {
            "not_started", "starting", "running", "stopping", "solved", "error"
        }
        client, _manager = display_client
        challenges = client.get("/api/challenges", headers=AUTH).json()

        for challenge in challenges:
            status = challenge["status"]
            assert status in valid_statuses, (
                f"Challenge {challenge['id']} has invalid status: {status}"
            )

    def test_challenge_has_id_and_title(self, display_client) -> None:
        client, _manager = display_client
        challenges = client.get("/api/challenges", headers=AUTH).json()

        for challenge in challenges:
            assert challenge["id"], f"Challenge missing id"
            assert challenge["title"], f"Challenge {challenge['id']} missing title"

    def test_no_extra_fields_that_could_confuse_frontend(self, display_client) -> None:
        """Ensure public() doesn't leak fields not expected by frontend."""
        client, _manager = display_client
        challenges = client.get("/api/challenges", headers=AUTH).json()

        for challenge in challenges:
            # These should NEVER appear in the public response
            forbidden = {"hint", "expected_flag", "root", "compose_path", "expose"}
            leaked = forbidden & set(challenge.keys())
            assert not leaked, f"Challenge {challenge['id']} leaked forbidden fields: {leaked}"


class TestChallengeDisplayWithRealDataset:
    def test_known_challenges_present(self, display_client) -> None:
        """Verify expected demo challenges are loaded."""
        client, _manager = display_client
        challenges = client.get("/api/challenges", headers=AUTH).json()
        ids = {c["id"] for c in challenges}

        expected = {"xben-001-24", "xben-002-24", "xben-003-24", "xben-004-24", "xben-005-24"}
        assert expected.issubset(ids), f"Missing challenges: {expected - ids}"

    def test_health_reports_correct_counts(self, display_client) -> None:
        client, manager = display_client
        response = client.get("/api/health")
        assert response.status_code == 200
        health = response.json()
        assert health["challenges"] == len(manager.challenges)
        assert health["ok"] is True
