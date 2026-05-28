from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# [1] JSONL = one JSON object per line; grep-friendly and append-only safe
# JSONL = 每行一个 JSON 对象；便于 grep 且追加写入安全
DEFAULT_EVENT_LOG = Path("logs/droplet-events.jsonl")
# [2] Redact sensitive values so audit logs never leak flags or tokens
# 对敏感值进行脱敏，确保审计日志不会泄漏 flag 或 token
SENSITIVE_KEYS = {"answer", "expected_flag", "flag", "secret", "token", "authorization"}


def utc_now() -> datetime:
    return datetime.now(UTC)


# [3] EventStore uses a dual-write strategy: disk (persistent) + memory (fast query)
# EventStore 使用双写策略：磁盘（持久化）+ 内存（快速查询）
class EventStore:
    """Append-only JSONL audit log for platform-visible benchmark events."""

    def __init__(self, path: Path | None = None, max_memory_events: int = 1000) -> None:
        configured = os.getenv("DROPLET_EVENT_LOG")
        self.path = path or (Path(configured) if configured else DEFAULT_EVENT_LOG)
        self.max_memory_events = max_memory_events
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    # [4] record() appends to disk first, then updates the in-memory cache
    # record() 先追加到磁盘，然后更新内存缓存
    def record(
        self,
        event_type: str,
        message: str,
        *,
        challenge_id: str | None = None,
        level: str = "info",
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": utc_now().isoformat(),
            "level": level,
            "event_type": event_type,
            "message": message,
            "challenge_id": challenge_id,
            "data": _sanitize(data or {}),
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            self._events.append(event)
            # [5] Trim memory cache to prevent unbounded growth
            # 裁剪内存缓存以防止无限制增长
            if len(self._events) > self.max_memory_events:
                self._events = self._events[-self.max_memory_events :]
        return event

    def list(self, *, challenge_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            events = list(self._events)
        if challenge_id:
            events = [event for event in events if event.get("challenge_id") == challenge_id]
        return events[-limit:]

    def clear_memory(self) -> None:
        with self._lock:
            self._events = []

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        loaded: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                loaded.append(item)
        self._events = loaded[-self.max_memory_events :]


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
