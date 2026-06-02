"""Tests for droplet.manager — pure logic methods that don't require Docker."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
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


def test_stop_challenge_allows_solved_with_runtime(manager, monkeypatch):
    c = _make_challenge()
    c.status = ChallengeStatus.solved
    c.solved = True
    c.compose_project = "droplet_TEST-001"
    c.work_dir = "/tmp/droplet_TEST-001"
    manager.challenges = {"TEST-001": c}
    calls = []
    monkeypatch.setattr(manager, "_do_stop_challenge", lambda cid: calls.append(cid))

    result = manager.stop_challenge("TEST-001")

    assert result.status == ChallengeStatus.stopping
    assert calls == ["TEST-001"]


# ── Flag judging tests ────────────────────────────────────────────────


def test_submit_correct_flag(manager):
    c = _make_challenge(expected_flag="flag{secret}")
    c.status = ChallengeStatus.running
    manager.challenges = {"TEST-001": c}

    result = manager.submit("TEST-001", "flag{secret}")

    assert result["accepted"] is True
    assert result["judged"] is True
    assert result["correct"] is True
    assert result["is_solved"] is True
    assert result["message"] == "correct flag"
    assert c.solved is True
    assert c.status == ChallengeStatus.running
    assert c.score == 1.0
    assert c.submission_count == 1


def test_submit_wrong_flag(manager):
    c = _make_challenge(expected_flag="flag{secret}")
    c.status = ChallengeStatus.running
    manager.challenges = {"TEST-001": c}

    result = manager.submit("TEST-001", "flag{wrong}")

    assert result["accepted"] is True
    assert result["judged"] is True
    assert result["correct"] is False
    assert result["is_solved"] is False
    assert result["message"] == "incorrect flag"
    assert c.solved is False
    assert c.status == ChallengeStatus.running
    assert c.submission_count == 1


def test_submit_no_flag_record_only(manager):
    c = _make_challenge(expected_flag=None)
    c.status = ChallengeStatus.running
    manager.challenges = {"TEST-001": c}

    result = manager.submit("TEST-001", "anything")

    assert result["accepted"] is True
    assert result["judged"] is False
    assert result["correct"] is None
    assert result["message"] == "submission recorded; no flag judge is configured"
    assert c.solved is False
    assert c.submission_count == 1


def test_submit_already_solved(manager):
    c = _make_challenge(expected_flag="flag{secret}")
    c.status = ChallengeStatus.running
    c.solved = True
    c.score = 1.0
    manager.challenges = {"TEST-001": c}

    result = manager.submit("TEST-001", "flag{secret}")

    assert result["judged"] is True
    assert result["correct"] is True
    assert result["is_solved"] is True
    assert c.submission_count == 1


def test_submit_correct_flag_with_hint_penalty(manager):
    c = _make_challenge(expected_flag="flag{secret}", hint="Some hint")
    c.status = ChallengeStatus.running
    c.hint_viewed = True
    c.hint_penalty = -0.2
    manager.challenges = {"TEST-001": c}

    result = manager.submit("TEST-001", "flag{secret}")

    assert result["correct"] is True
    assert result["score_after_hint_penalty"] == 0.8
    assert c.score == 0.8


def test_submit_flag_case_sensitive(manager):
    c = _make_challenge(expected_flag="flag{Secret}")
    c.status = ChallengeStatus.running
    manager.challenges = {"TEST-001": c}

    result = manager.submit("TEST-001", "flag{secret}")
    assert result["correct"] is False

    result2 = manager.submit("TEST-001", "flag{Secret}")
    assert result2["correct"] is True
