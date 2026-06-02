"""Tests for droplet.models — Challenge model, ChallengeStatus, now()."""

from __future__ import annotations

from datetime import UTC, datetime

from droplet.models import (
    TERMINAL_STATUSES,
    Challenge,
    ChallengeStatus,
    now,
)


def test_now_returns_utc():
    t = now()
    assert t.tzinfo == UTC


def test_challenge_status_enum_values():
    assert ChallengeStatus.not_started.value == "not_started"
    assert ChallengeStatus.starting.value == "starting"
    assert ChallengeStatus.running.value == "running"
    assert ChallengeStatus.stopping.value == "stopping"
    assert ChallengeStatus.solved.value == "solved"
    assert ChallengeStatus.error.value == "error"


def test_terminal_statuses():
    assert ChallengeStatus.solved in TERMINAL_STATUSES
    assert ChallengeStatus.error in TERMINAL_STATUSES
    assert ChallengeStatus.running not in TERMINAL_STATUSES
    assert ChallengeStatus.not_started not in TERMINAL_STATUSES


def _make_challenge(**kwargs):
    defaults = {
        "id": "TEST-001",
        "title": "Test Challenge",
        "description": "A test challenge",
        "category": "web",
        "task_type": "ctf",
        "difficulty": "easy",
        "root": "/tmp/test",
        "compose_path": "/tmp/test/docker-compose.yml",
        "expose": [{"container_port": 80}],
    }
    defaults.update(kwargs)
    return Challenge(**defaults)


def test_challenge_default_status():
    c = _make_challenge()
    assert c.status == ChallengeStatus.not_started
    assert c.solved is False
    assert c.score == 0.0
    assert c.submission_count == 0


def test_challenge_public_excludes_hint():
    c = _make_challenge(hint="secret hint")
    public = c.public()
    assert "hint" not in public
    assert public["has_hint"] is True


def test_challenge_public_no_hint():
    c = _make_challenge(hint=None)
    public = c.public()
    assert public["has_hint"] is False


def test_challenge_public_fields():
    c = _make_challenge()
    public = c.public()
    assert public["id"] == "TEST-001"
    assert public["status"] == "not_started"
    assert public["solved"] is False
    assert public["started_at"] is None
    assert public["finished_at"] is None


def test_challenge_public_excludes_expected_flag():
    c = _make_challenge(expected_flag="flag{secret}")
    public = c.public()
    assert "expected_flag" not in public
    assert public["has_expected_flag"] is True


def test_challenge_public_no_expected_flag():
    c = _make_challenge(expected_flag=None)
    public = c.public()
    assert public["has_expected_flag"] is False


def test_challenge_public_with_timestamps():
    c = _make_challenge()
    c.started_at = datetime(2026, 1, 1, tzinfo=UTC)
    public = c.public()
    assert "2026-01-01" in public["started_at"]


def test_challenge_status_transitions():
    c = _make_challenge()
    c.status = ChallengeStatus.starting
    assert c.status == ChallengeStatus.starting
    c.status = ChallengeStatus.running
    assert c.status == ChallengeStatus.running
    c.status = ChallengeStatus.solved
    assert c.status in TERMINAL_STATUSES
