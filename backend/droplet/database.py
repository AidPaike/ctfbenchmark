from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator

from datetime import UTC, datetime
from pathlib import Path
from typing import Generator

from sqlmodel import Field, Session, SQLModel, create_engine, select, UniqueConstraint


# [1] Resolve project root so the database is always anchored to the repo root,
#     regardless of which working directory Python is launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# [2] SQLite file path; override via env var for tests
# SQLite 文件路径；可通过环境变量覆盖以用于测试
DATABASE_PATH = Path(os.getenv("DROPLET_DATABASE_PATH", _PROJECT_ROOT / "data" / "droplet.db"))

# [3] SQLAlchemy engine with WAL mode for better concurrent read performance
# WAL 模式提升并发读取性能
_engine = None
_engine_path = None


def get_engine():
    global _engine, _engine_path
    raw = os.getenv("DROPLET_DATABASE_PATH")
    current_path = Path(raw) if raw else _PROJECT_ROOT / "data" / "droplet.db"
    if _engine is None or _engine_path != current_path:
        _engine_path = current_path
        _engine_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{_engine_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
    return _engine


def reset_engine() -> None:
    global _engine, _engine_path
    _engine = None
    _engine_path = None


def init_db() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)


def _ensure_sqlite_columns(engine) -> None:
    """Apply small additive SQLite migrations for existing local databases."""
    with engine.begin() as connection:
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        if "events" in tables:
            event_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(events)")}
            if "archived" not in event_columns:
                connection.exec_driver_sql("ALTER TABLE events ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0")


# [3] SQLModel table for audit events — mirrors the JSONL schema exactly
# 审计事件 SQLModel 表 —— 与 JSONL 结构完全一致
class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(primary_key=True, max_length=32)
    timestamp: str = Field(index=True)
    level: str = Field(max_length=16, default="info")
    event_type: str = Field(max_length=64, index=True)
    message: str
    challenge_id: str | None = Field(default=None, max_length=64, index=True)
    data: str = Field(default="{}")
    session_id: int = Field(default=1, index=True)
    archived: bool = Field(default=False, index=True)


# [4] System log table for structured application logging
# 系统日志表，用于结构化应用日志
class SystemLog(SQLModel, table=True):
    __tablename__ = "system_logs"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    level: str = Field(max_length=10, index=True)
    logger: str = Field(max_length=64, index=True)
    message: str
    source_file: str | None = Field(default=None, max_length=256)
    source_line: int | None = Field(default=None)
    exception: str | None = Field(default=None)
    data: str = Field(default="{}")


# [5] Challenge progress persistence — tagged by session so resets are logical, not physical
# 题目进度持久化 —— 用 session 标签实现逻辑重置，数据物理保留
class ChallengeProgress(SQLModel, table=True):
    __tablename__ = "challenge_progress"

    id: int | None = Field(default=None, primary_key=True)
    challenge_id: str = Field(max_length=64, index=True)
    session_id: int = Field(default=1, index=True)
    solved: bool = Field(default=False)
    hint_viewed: bool = Field(default=False)
    hint_penalty: float = Field(default=0.0)
    submission_count: int = Field(default=0)
    score: float = Field(default=0.0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        UniqueConstraint("challenge_id", "session_id", name="uq_progress_challenge_session"),
    )


# [6] Submission history — every answer attempt is preserved across resets
# 提交历史 —— 每次答题尝试都会保留，即使重置也不会删除
class Submission(SQLModel, table=True):
    __tablename__ = "submissions"

    id: int | None = Field(default=None, primary_key=True)
    challenge_id: str = Field(max_length=64, index=True)
    session_id: int = Field(default=1, index=True)
    answer: str
    correct: bool
    score_before: float = Field(default=0.0)
    score_after: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


# [7] Key-value store for application-level state (e.g. current session id)
# 应用级键值存储（如当前 session id）
class AppState(SQLModel, table=True):
    __tablename__ = "app_state"

    key: str = Field(primary_key=True, max_length=64)
    value_int: int | None = Field(default=None)
    value_str: str | None = Field(default=None, max_length=256)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


# [8] Session helpers — resets increment the session id instead of deleting rows
# Session 辅助函数 —— 重置时递增 session id，而不是删除数据行
_CURRENT_SESSION_CACHE: int | None = None


def get_current_session_id() -> int:
    """Return the active session id; creates one if missing."""
    global _CURRENT_SESSION_CACHE
    if _CURRENT_SESSION_CACHE is not None:
        return _CURRENT_SESSION_CACHE
    engine = get_engine()
    with Session(engine) as session:
        state = session.get(AppState, "current_session_id")
        if state is None:
            state = AppState(key="current_session_id", value_int=1)
            session.add(state)
            session.commit()
            _CURRENT_SESSION_CACHE = 1
            return 1
        _CURRENT_SESSION_CACHE = state.value_int or 1
        return _CURRENT_SESSION_CACHE


def increment_session_id() -> int:
    """Increment the global session id and clear the local cache."""
    global _CURRENT_SESSION_CACHE
    engine = get_engine()
    with Session(engine) as session:
        state = session.get(AppState, "current_session_id")
        if state is None:
            state = AppState(key="current_session_id", value_int=2)
            session.add(state)
            session.commit()
            _CURRENT_SESSION_CACHE = 2
            return 2
        current = state.value_int or 1
        state.value_int = current + 1
        session.add(state)
        session.commit()
        _CURRENT_SESSION_CACHE = current + 1
        return _CURRENT_SESSION_CACHE


def reset_session_cache() -> None:
    """Clear the cached session id (useful in tests)."""
    global _CURRENT_SESSION_CACHE
    _CURRENT_SESSION_CACHE = None


# [9] Optional migration: copy historical JSONL events into SQLite on first init
# 可选迁移：首次初始化时将历史 JSONL 事件复制到 SQLite

def migrate_jsonl_to_sqlite(jsonl_path: Path) -> int:
    if not jsonl_path.exists():
        return 0

    engine = get_engine()
    with Session(engine) as session:
        existing_count = session.exec(select(Event)).first()
        if existing_count is not None:
            return 0

        migrated = 0
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue

            event = Event(
                id=raw.get("id", ""),
                timestamp=raw.get("timestamp", ""),
                level=raw.get("level", "info"),
                event_type=raw.get("event_type", ""),
                message=raw.get("message", ""),
                challenge_id=raw.get("challenge_id"),
                data=json.dumps(raw.get("data", {}), ensure_ascii=False, default=str),
            )
            session.add(event)
            migrated += 1

        session.commit()
        return migrated
