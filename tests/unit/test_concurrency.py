from __future__ import annotations

import time
from pathlib import Path

import pytest

from droplet.models import Challenge, ChallengeStatus
from droplet.manager import DropletManager


def _make_challenge(template: Path, challenge_id: str = "demo") -> Challenge:
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
        title=challenge_id.title(),
        description="Demo challenge",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        root=str(template),
        compose_path=str(template / "docker-compose.yml"),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
    )


def test_start_challenge_sets_starting_state_and_spawns_background_thread(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"
    challenge = _make_challenge(template)

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    manager.challenges = {challenge.id: challenge}

    started = []

    def fake_do_start(cid: str) -> None:
        started.append(cid)

    monkeypatch.setattr(manager, "_do_start_challenge", fake_do_start)

    result = manager.start_challenge(challenge.id)

    assert result.status == ChallengeStatus.starting
    assert started == [challenge.id]


def test_start_challenge_returns_existing_when_already_starting(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"
    challenge = _make_challenge(template)
    challenge.status = ChallengeStatus.starting

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    manager.challenges = {challenge.id: challenge}

    calls = []
    monkeypatch.setattr(manager, "_do_start_challenge", lambda cid: calls.append(cid))

    result = manager.start_challenge(challenge.id)

    assert result.status == ChallengeStatus.starting
    assert calls == []


def test_start_challenge_returns_existing_when_already_running(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"
    challenge = _make_challenge(template)
    challenge.status = ChallengeStatus.running

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    manager.challenges = {challenge.id: challenge}

    calls = []
    monkeypatch.setattr(manager, "_do_start_challenge", lambda cid: calls.append(cid))

    result = manager.start_challenge(challenge.id)

    assert result.status == ChallengeStatus.running
    assert calls == []


def test_start_challenge_enforces_max_concurrent_limit(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    manager.max_concurrent = 2

    # Create 3 challenges
    for i in range(3):
        c = _make_challenge(tmp_path / f"template_{i}", f"demo_{i}")
        manager.challenges[c.id] = c

    # Mark first two as running
    manager.challenges["demo_0"].status = ChallengeStatus.running
    manager.challenges["demo_1"].status = ChallengeStatus.running

    calls = []
    monkeypatch.setattr(manager, "_do_start_challenge", lambda cid: calls.append(cid))

    with pytest.raises(RuntimeError, match="Maximum concurrent environments"):
        manager.start_challenge("demo_2")

    assert calls == []


def test_start_challenge_counts_starting_towards_limit(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    manager.max_concurrent = 2

    for i in range(3):
        c = _make_challenge(tmp_path / f"template_{i}", f"demo_{i}")
        manager.challenges[c.id] = c

    # One running, one starting
    manager.challenges["demo_0"].status = ChallengeStatus.running
    manager.challenges["demo_1"].status = ChallengeStatus.starting

    calls = []
    monkeypatch.setattr(manager, "_do_start_challenge", lambda cid: calls.append(cid))

    with pytest.raises(RuntimeError, match="Maximum concurrent environments"):
        manager.start_challenge("demo_2")

    assert calls == []


def test_stop_challenge_clears_starting_state(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"
    challenge = _make_challenge(template)
    challenge.status = ChallengeStatus.starting

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    manager.challenges = {challenge.id: challenge}

    monkeypatch.setattr(manager, "_stop_compose", lambda c: None)

    result = manager.stop_challenge(challenge.id)

    assert result.status == ChallengeStatus.not_started


def test_stats_includes_starting_count(tmp_path) -> None:
    template = tmp_path / "template"

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")

    for i in range(3):
        c = _make_challenge(tmp_path / f"template_{i}", f"demo_{i}")
        manager.challenges[c.id] = c

    manager.challenges["demo_0"].status = ChallengeStatus.running
    manager.challenges["demo_1"].status = ChallengeStatus.starting
    manager.challenges["demo_2"].status = ChallengeStatus.not_started

    stats = manager.stats()

    assert stats["running"] == 1
    assert stats["starting"] == 1
    assert stats["total_challenges"] == 3


def test_start_all_collects_skipped_limit(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    manager.max_concurrent = 1

    for i in range(3):
        c = _make_challenge(tmp_path / f"template_{i}", f"demo_{i}")
        manager.challenges[c.id] = c

    monkeypatch.setattr(manager, "_do_start_challenge", lambda cid: None)

    result = manager.start_all()

    assert result["started"] == ["demo_0"]
    assert result["skipped_limit"] == ["demo_1", "demo_2"]
    assert result["errors"] == {}
