from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, desc, select

from droplet.database import Event, get_current_session_id, get_engine


# [1] Redact sensitive values so audit logs never leak flags or tokens
# 对敏感值进行脱敏，确保审计日志不会泄漏 flag 或 token
SENSITIVE_KEYS = {"answer", "expected_flag", "flag", "secret", "token", "authorization"}

# [2] Default path retained for optional JSONL migration on first boot
# 保留默认路径以便首次启动时进行可选的 JSONL 迁移
DEFAULT_EVENT_LOG = Path("logs/droplet-events.jsonl")


def utc_now() -> datetime:
    return datetime.now(UTC)


# [3] EventStore backed by SQLite (via SQLModel) for persistent, queryable audit logs
# EventStore 后端使用 SQLite（通过 SQLModel），实现持久化、可查询的审计日志
class EventStore:
    """SQLite-backed audit log for platform-visible benchmark events."""

    def __init__(self, path: Path | None = None, max_memory_events: int = 1000) -> None:
        # path is retained for compatibility but no longer used for writes
        self.path = path or DEFAULT_EVENT_LOG
        self.max_memory_events = max_memory_events
        self._engine = get_engine()
        # Ensure tables exist for tests and direct instantiation
        from droplet.database import init_db

        init_db()

    # [4] record() persists to SQLite; retains same return shape as before
    # record() 持久化到 SQLite；保持与之前相同的返回结构
    def record(
        self,
        event_type: str,
        message: str,
        *,
        challenge_id: str | None = None,
        level: str = "info",
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = get_current_session_id()
        event = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": utc_now().isoformat(),
            "level": level,
            "event_type": event_type,
            "message": message,
            "challenge_id": challenge_id,
            "data": _sanitize(data or {}),
            "session_id": session_id,
        }
        db_event = Event(
            id=event["id"],
            timestamp=event["timestamp"],
            level=event["level"],
            event_type=event["event_type"],
            message=event["message"],
            challenge_id=event["challenge_id"],
            data=json.dumps(event["data"], ensure_ascii=False, default=str),
            session_id=session_id,
        )
        with Session(self._engine) as session:
            session.add(db_event)
            session.commit()
        return event

    # [5] list() queries SQLite with optional challenge filter and limit
    # list() 从 SQLite 查询，支持可选的题目过滤和数量限制
    def list(self, *, challenge_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        session_id = get_current_session_id()
        with Session(self._engine) as session:
            query = select(Event).where(Event.session_id == session_id).order_by(desc(Event.timestamp))
            if challenge_id:
                query = query.where(Event.challenge_id == challenge_id)
            query = query.limit(limit)
            results = session.exec(query).all()
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "level": r.level,
                    "event_type": r.event_type,
                    "message": r.message,
                    "challenge_id": r.challenge_id,
                    "data": json.loads(r.data) if r.data else {},
                }
                for r in results
            ]

    def clear_memory(self) -> None:
        # No-op: SQLite persists everything; clearMemory has no in-memory cache to clear
        pass


# [6] Recursively sanitize nested dicts/lists so no sensitive key slips through
# 递归地对嵌套的字典/列表进行脱敏，防止敏感键泄漏
def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(part in lowered for part in SENSITIVE_KEYS)


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            text_key = str(key)
            if _is_sensitive_key(text_key):
                sanitized[text_key] = "<redacted>"
            else:
                sanitized[text_key] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
