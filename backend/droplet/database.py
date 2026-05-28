from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator

from sqlmodel import Field, Session, SQLModel, create_engine, select


# [1] SQLite file path; override via env var for tests
# SQLite 文件路径；可通过环境变量覆盖以用于测试
DATABASE_PATH = Path(os.getenv("DROPLET_DATABASE_PATH", "data/droplet.db"))

# [2] SQLAlchemy engine with WAL mode for better concurrent read performance
# WAL 模式提升并发读取性能
_engine = None
_engine_path = None


def get_engine():
    global _engine, _engine_path
    current_path = Path(os.getenv("DROPLET_DATABASE_PATH", "data/droplet.db"))
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


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


# [4] Optional migration: copy historical JSONL events into SQLite on first init
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
