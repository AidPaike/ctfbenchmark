from __future__ import annotations

import json
from pathlib import Path

from droplet.events import EventStore


def test_event_store_persists_to_sqlite_and_redacts_sensitive_fields(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")

    event = store.record(
        "submission_recorded",
        "submitted",
        challenge_id="xben-001-24",
        data={"answer": "flag{secret}", "judged": False, "nested": {"token": "abc"}},
    )

    assert event["data"]["answer"] == "<redacted>"
    assert event["data"]["nested"]["token"] == "<redacted>"

    # Verify persisted to SQLite
    events = store.list(challenge_id="xben-001-24")
    assert len(events) == 1
    persisted = events[0]
    assert persisted["event_type"] == "submission_recorded"
    assert persisted["data"]["judged"] is False
    assert persisted["data"]["answer"] == "<redacted>"


def test_event_store_filters_by_challenge(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.record("challenge_started", "one", challenge_id="a")
    store.record("challenge_started", "two", challenge_id="b")

    events = store.list(challenge_id="b")

    assert [event["message"] for event in events] == ["two"]


def test_event_store_respects_limit(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    for i in range(5):
        store.record("agent_event", f"event-{i}", challenge_id="test")

    events = store.list(challenge_id="test", limit=3)

    assert len(events) == 3
    # Most recent first (descending order)
    assert [e["message"] for e in events] == ["event-4", "event-3", "event-2"]


def test_event_store_list_without_challenge_id_returns_all(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.record("challenge_started", "global", challenge_id=None)
    store.record("challenge_started", "scoped", challenge_id="test")

    events = store.list(limit=10)

    assert len(events) == 2


def test_event_store_isolates_by_session_id(tmp_path: Path) -> None:
    """Events from a previous session should not appear after reset."""
    from droplet.database import get_current_session_id, increment_session_id

    store = EventStore(tmp_path / "events.jsonl")
    store.record("challenge_started", "old session event", challenge_id="test")

    # Verify event is visible in current session
    assert len(store.list(challenge_id="test")) == 1

    # Simulate reset-all by incrementing session
    increment_session_id()

    # Old event should no longer be visible
    assert len(store.list(challenge_id="test")) == 0

    # New events go into the new session
    store.record("challenge_started", "new session event", challenge_id="test")
    assert len(store.list(challenge_id="test")) == 1
    assert store.list(challenge_id="test")[0]["message"] == "new session event"
