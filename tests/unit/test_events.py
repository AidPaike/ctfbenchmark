from __future__ import annotations

import json
from pathlib import Path

from droplet.events import EventStore


def test_event_store_writes_jsonl_and_redacts_sensitive_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    store = EventStore(log_path)

    event = store.record(
        "submission_recorded",
        "submitted",
        challenge_id="xben-001-24",
        data={"answer": "flag{secret}", "judged": False, "nested": {"token": "abc"}},
    )

    assert event["data"]["answer"] == "<redacted>"
    assert event["data"]["nested"]["token"] == "<redacted>"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    persisted = json.loads(lines[0])
    assert persisted["event_type"] == "submission_recorded"
    assert persisted["data"]["judged"] is False


def test_event_store_filters_by_challenge(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.record("challenge_started", "one", challenge_id="a")
    store.record("challenge_started", "two", challenge_id="b")

    events = store.list(challenge_id="b")

    assert [event["message"] for event in events] == ["two"]
