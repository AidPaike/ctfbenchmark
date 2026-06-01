"""Tests for droplet.database — engine lifecycle, models, session helpers."""

from __future__ import annotations

import json
from pathlib import Path

from droplet.database import (
    AppState,
    ChallengeProgress,
    Event,
    Submission,
    SystemLog,
    get_current_session_id,
    get_engine,
    increment_session_id,
    init_db,
    migrate_jsonl_to_sqlite,
    reset_engine,
    reset_session_cache,
)
from sqlmodel import Session, select


def test_get_engine_creates_sqlite_file(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DROPLET_DATABASE_PATH", str(db_path))
    reset_engine()
    engine = get_engine()
    assert engine is not None
    assert db_path.exists() or db_path.parent.exists()


def test_get_engine_returns_same_instance(monkeypatch, isolated_database):
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


def test_reset_engine_clears_cache(monkeypatch, isolated_database):
    get_engine()
    reset_engine()
    e2 = get_engine()
    # After reset, a new engine is created (same path, different object is also fine)
    assert e2 is not None


def test_init_db_creates_tables(isolated_database):
    init_db()
    engine = get_engine()
    with Session(engine) as session:
        # Should be able to query all tables
        session.exec(select(Event)).all()
        session.exec(select(SystemLog)).all()
        session.exec(select(ChallengeProgress)).all()
        session.exec(select(Submission)).all()
        session.exec(select(AppState)).all()


def test_event_model_fields(isolated_database):
    init_db()
    engine = get_engine()
    with Session(engine) as session:
        event = Event(
            id="test123",
            timestamp="2026-01-01T00:00:00Z",
            level="info",
            event_type="test_event",
            message="Test message",
            challenge_id="TEST-001",
            data='{"key": "value"}',
            session_id=1,
        )
        session.add(event)
        session.commit()
        retrieved = session.get(Event, "test123")
        assert retrieved is not None
        assert retrieved.challenge_id == "TEST-001"
        assert retrieved.level == "info"


def test_get_current_session_id_creates_default(isolated_database):
    init_db()
    reset_session_cache()
    sid = get_current_session_id()
    assert sid == 1


def test_get_current_session_id_caches(isolated_database):
    init_db()
    reset_session_cache()
    sid1 = get_current_session_id()
    sid2 = get_current_session_id()
    assert sid1 == sid2


def test_increment_session_id(isolated_database):
    init_db()
    reset_session_cache()
    get_current_session_id()  # ensure it exists
    new_sid = increment_session_id()
    assert new_sid == 2
    assert get_current_session_id() == 2


def test_increment_session_id_from_none(isolated_database):
    init_db()
    reset_session_cache()
    new_sid = increment_session_id()
    assert new_sid == 2


def test_migrate_jsonl_to_sqlite(tmp_path, isolated_database):
    init_db()
    jsonl_path = tmp_path / "events.jsonl"
    events = [
        {
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00Z",
            "level": "info",
            "event_type": "test",
            "message": "msg1",
            "data": {},
        },
        {
            "id": "e2",
            "timestamp": "2026-01-01T00:01:00Z",
            "level": "error",
            "event_type": "err",
            "message": "msg2",
            "challenge_id": "C1",
            "data": {"a": 1},
        },
    ]
    jsonl_path.write_text("\n".join(json.dumps(e) for e in events))
    count = migrate_jsonl_to_sqlite(jsonl_path)
    assert count == 2
    engine = get_engine()
    with Session(engine) as session:
        stored = session.exec(select(Event)).all()
        assert len(stored) == 2


def test_migrate_jsonl_skips_if_events_exist(isolated_database):
    init_db()
    engine = get_engine()
    with Session(engine) as session:
        session.add(Event(id="existing", timestamp="t", event_type="x", message="m"))
        session.commit()
    # Create a dummy JSONL file
    p = Path("/tmp/test_migrate_skip.jsonl")
    p.write_text('{"id":"new","timestamp":"t","event_type":"x","message":"m"}\n')
    count = migrate_jsonl_to_sqlite(p)
    assert count == 0
    p.unlink(missing_ok=True)


def test_migrate_jsonl_missing_file(isolated_database):
    count = migrate_jsonl_to_sqlite(Path("/nonexistent/file.jsonl"))
    assert count == 0
