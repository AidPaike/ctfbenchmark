from __future__ import annotations

from droplet.database import (
    ChallengeProgress,
    Submission,
    get_current_session_id,
    get_engine,
    init_db,
    reset_session_cache,
)
from droplet.manager import DropletManager
from droplet.models import Challenge, ChallengeStatus
from sqlmodel import Session, select


def _make_manager(tmp_path):
    """Create a manager with a dummy challenge for persistence tests."""
    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    challenge = Challenge(
        id="demo",
        title="Demo",
        description="Demo",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        root=str(tmp_path),
        compose_path=str(tmp_path / "docker-compose.yml"),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
        expected_flag="FLAG{test}",
    )
    manager.challenges = {"demo": challenge}
    return manager, challenge


def test_persist_progress_writes_to_db(tmp_path) -> None:
    """_persist_progress should create or update a ChallengeProgress row."""
    manager, challenge = _make_manager(tmp_path)
    challenge.solved = True
    challenge.score = 0.9
    challenge.submission_count = 3
    challenge.hint_viewed = True
    challenge.hint_penalty = -0.1

    manager._persist_progress(challenge)

    session_id = get_current_session_id()
    engine = get_engine()
    with Session(engine) as session:
        stmt = select(ChallengeProgress).where(
            ChallengeProgress.challenge_id == "demo",
            ChallengeProgress.session_id == session_id,
        )
        prog = session.exec(stmt).first()
        assert prog is not None
        assert prog.solved is True
        assert prog.score == 0.9
        assert prog.submission_count == 3
        assert prog.hint_viewed is True
        assert prog.hint_penalty == -0.1


def test_restore_progress_reads_from_db(tmp_path) -> None:
    """_restore_progress should load persisted state onto in-memory challenges."""
    manager, challenge = _make_manager(tmp_path)

    # Pre-populate DB with a solved challenge
    session_id = get_current_session_id()
    engine = get_engine()
    with Session(engine) as session:
        prog = ChallengeProgress(
            challenge_id="demo",
            session_id=session_id,
            solved=True,
            score=0.85,
            submission_count=5,
            hint_viewed=True,
            hint_penalty=-0.2,
        )
        session.add(prog)
        session.commit()

    # Challenge starts with defaults
    assert challenge.solved is False
    assert challenge.score == 0.0

    manager._restore_progress()

    assert challenge.solved is True
    assert challenge.score == 0.85
    assert challenge.submission_count == 5
    assert challenge.hint_viewed is True
    assert challenge.hint_penalty == -0.2
    assert challenge.status == ChallengeStatus.solved


def test_record_submission_creates_row(tmp_path) -> None:
    """_record_submission should insert a Submission row."""
    manager, challenge = _make_manager(tmp_path)

    manager._record_submission(challenge, "FLAG{guess}", False, 0.0, 0.0)
    manager._record_submission(challenge, "FLAG{test}", True, 1.0, 0.9)

    session_id = get_current_session_id()
    engine = get_engine()
    with Session(engine) as session:
        stmt = select(Submission).where(
            Submission.challenge_id == "demo",
            Submission.session_id == session_id,
        )
        rows = list(session.exec(stmt))
        assert len(rows) == 2
        assert rows[0].answer == "FLAG{guess}"
        assert rows[0].correct is False
        assert rows[1].answer == "FLAG{test}"
        assert rows[1].correct is True
        assert rows[1].score_after == 0.9


def test_get_submissions_returns_current_session_only(tmp_path) -> None:
    """get_submissions should only return rows for the active session."""
    manager, challenge = _make_manager(tmp_path)

    # Insert submission for current session
    manager._record_submission(challenge, "FLAG{a}", True, 1.0, 1.0)

    # Insert submission for an old session (should not appear)
    engine = get_engine()
    with Session(engine) as session:
        old = Submission(
            challenge_id="demo",
            session_id=999,
            answer="FLAG{old}",
            correct=False,
            score_before=0.0,
            score_after=0.0,
        )
        session.add(old)
        session.commit()

    results = manager.get_submissions("demo", limit=10)
    assert len(results) == 1
    assert results[0]["answer"] == "FLAG{a}"


def test_clear_progress_resets_current_session(tmp_path) -> None:
    """_clear_progress should reset the current session's progress without deleting the row."""
    manager, challenge = _make_manager(tmp_path)
    challenge.solved = True
    challenge.score = 0.8
    challenge.submission_count = 2
    manager._persist_progress(challenge)

    manager._clear_progress("demo")

    # In-memory state reset
    assert challenge.solved is False
    assert challenge.score == 0.0
    assert challenge.submission_count == 0

    # DB row reset but still exists
    session_id = get_current_session_id()
    engine = get_engine()
    with Session(engine) as session:
        stmt = select(ChallengeProgress).where(
            ChallengeProgress.challenge_id == "demo",
            ChallengeProgress.session_id == session_id,
        )
        prog = session.exec(stmt).first()
        assert prog is not None
        assert prog.solved is False
        assert prog.score == 0.0


def test_reset_all_increments_session_and_isolates_progress(tmp_path) -> None:
    """reset_all_challenges should increment session_id so old progress is hidden."""
    manager, challenge = _make_manager(tmp_path)
    challenge.solved = True
    challenge.score = 1.0
    manager._persist_progress(challenge)

    old_session = get_current_session_id()
    result = manager.reset_all_challenges()
    new_session = result["new_session_id"]

    assert new_session == old_session + 1
    assert challenge.solved is False
    assert challenge.score == 0.0

    # Old progress still in DB but not visible to current session
    engine = get_engine()
    with Session(engine) as session:
        stmt = select(ChallengeProgress).where(
            ChallengeProgress.challenge_id == "demo",
            ChallengeProgress.session_id == old_session,
        )
        old_prog = session.exec(stmt).first()
        assert old_prog is not None
        assert old_prog.solved is True

        stmt2 = select(ChallengeProgress).where(
            ChallengeProgress.challenge_id == "demo",
            ChallengeProgress.session_id == new_session,
        )
        new_prog = session.exec(stmt2).first()
        assert new_prog is None
