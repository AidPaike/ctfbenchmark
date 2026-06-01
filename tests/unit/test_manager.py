"""Tests for droplet.manager — pure logic methods that don't require Docker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from droplet.events import EventStore
from droplet.manager import DropletManager, _normalise_no_proxy, _normalise_proxy, _ratio
from droplet.models import Challenge, ChallengeStatus


# ── Helper ──────────────────────────────────────────────────────────

def _make_challenge(**kwargs):
    defaults = {
        "id": "TEST-001",
        "title": "Test",
        "description": "desc",
        "category": "web",
        "task_type": "ctf",
        "difficulty": "easy",
        "root": "/tmp/test",
        "compose_path": "/tmp/test/docker-compose.yml",
        "expose": [{"container_port": 80}],
    }
    defaults.update(kwargs)
    return Challenge(**defaults)


# ── Module-level helpers ─────────────────────────────────────────────

def test_normalise_proxy_none():
    assert _normalise_proxy(None) is None


def test_normalise_proxy_valid():
    result = _normalise_proxy("http://proxy:8080")
    assert result == "http://proxy:8080"


def test_normalise_no_proxy_merges():
    result = _normalise_no_proxy("a.com,b.com", "default.com")
    assert "a.com" in result
    assert "b.com" in result
    assert "default.com" in result


def test_ratio_zero_denominator():
    assert _ratio(0, 0) == 0.0


def test_ratio_normal():
    assert _ratio(1, 4) == 0.25


# ── Manager tests (with mocked Docker) ──────────────────────────────

@pytest.fixture
def manager(tmp_path, isolated_database):
    """Create a DropletManager with mocked Docker dependencies."""
    ds_root = tmp_path / "datasets"
    ds_root.mkdir()
    work_root = tmp_path / "work"
    work_root.mkdir()

    mock_loader = MagicMock()
    mock_loader.load.return_value = {}

    mgr = DropletManager(
        dataset_root=ds_root,
        work_root=work_root,
        dataset_loader=mock_loader,
    )
    return mgr


def test_manager_init(manager):
    assert manager.challenges == {}
    assert manager.public_host == "127.0.0.1"


def test_list_challenges_empty(manager):
    assert manager.list_challenges() == []


def test_get_challenge_not_found(manager):
    with pytest.raises(KeyError, match="not found"):
        manager.get_challenge("NONEXISTENT")


def test_stats_empty(manager):
    s = manager.stats()
    assert s["total_challenges"] == 0
    assert s["solved"] == 0
    assert s["running"] == 0
    assert s["overall_score"] == 0.0


def test_stats_with_challenges(manager):
    c1 = _make_challenge(id="C1")
    c1.solved = True
    c2 = _make_challenge(id="C2")
    c2.status = ChallengeStatus.running
    c3 = _make_challenge(id="C3")
    manager.challenges = {"C1": c1, "C2": c2, "C3": c3}

    s = manager.stats()
    assert s["total_challenges"] == 3
    assert s["solved"] == 1
    assert s["running"] == 1


def test_submit_not_running(manager):
    c = _make_challenge()
    c.status = ChallengeStatus.not_started
    manager.challenges = {"TEST-001": c}
    with pytest.raises(ValueError, match="not running"):
        manager.submit("TEST-001", "FLAG{test}")


def test_submit_running(manager):
    c = _make_challenge()
    c.status = ChallengeStatus.running
    manager.challenges = {"TEST-001": c}
    result = manager.submit("TEST-001", "FLAG{test}")
    assert result["accepted"] is True
    assert result["judged"] is False
    assert c.submission_count == 1


def test_hint_not_available(manager):
    c = _make_challenge(hint=None)
    manager.challenges = {"TEST-001": c}
    with pytest.raises(ValueError, match="not available"):
        manager.hint("TEST-001")


def test_hint_first_use(manager):
    c = _make_challenge(hint="Some hint text")
    manager.challenges = {"TEST-001": c}
    result = manager.hint("TEST-001")
    assert result["content"] == "Some hint text"
    assert result["penalty"] == -0.1
    assert result["first_use"] is True
    assert c.hint_viewed is True
    assert c.hint_penalty == -0.1


def test_hint_second_use(manager):
    c = _make_challenge(hint="Some hint text")
    c.hint_viewed = True
    c.hint_penalty = -0.1
    manager.challenges = {"TEST-001": c}
    result = manager.hint("TEST-001")
    assert result["penalty"] == 0.0
    assert result["first_use"] is False
    assert c.hint_penalty == -0.1  # no additional penalty


def test_prefetch_progress_not_running(manager):
    p = manager.prefetch_progress()
    assert p["running"] is False
    assert p["total"] == 0


def test_reset_all_challenges(manager):
    c1 = _make_challenge(id="C1")
    c1.solved = True
    c2 = _make_challenge(id="C2")
    manager.challenges = {"C1": c1, "C2": c2}
    result = manager.reset_all_challenges()
    assert "new_session_id" in result
    assert result["reset"] is True
