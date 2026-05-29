from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# [1] Use UTC to a void timezone issues in logs and APIs
# 使用 UTC 避免日志和 API 中的时区问题
def now() -> datetime:
    return datetime.now(UTC)


# [2] str+Enum makes JSON serialization trivial (just .value)
# str+Enum 让 JSON 序列化变得简单（直接用 .value）
class ChallengeStatus(str, Enum):
    not_started = "not_started"
    starting = "starting"
    running = "running"
    stopping = "stopping"
    solved = "solved"
    error = "error"


# [3] Terminal statuses mean no further state transitions are expected
# 终态表示不再期望有进一步的状态转换
TERMINAL_STATUSES = {ChallengeStatus.solved, ChallengeStatus.error}


# [4] One model holds both static metadata and mutable runtime state.
# Separation is done by field grouping + the public() filter method.
# 一个模型同时承载静态元数据和可变运行时状态。
# 通过字段分组 + public() 过滤方法来分离。
class Challenge(BaseModel):
    """A challenge with its runtime state and scoring state."""

    # --- Static metadata (loaded from dataset, never changes) ---
    # 静态元数据（从数据集加载，永不改变）
    id: str
    title: str
    description: str
    category: str
    task_type: str
    difficulty: str
    dataset_id: str = ""
    tags: list[str] = Field(default_factory=list)
    hint: str | None = None
    judge_mode: str = "record_only"
    root: str
    compose_path: str
    expose: list[dict[str, Any]]

    # --- Runtime state (mutable) ---
    # 运行时状态（可变）
    status: ChallengeStatus = ChallengeStatus.not_started
    target_url: str | None = None
    ports: list[int] = Field(default_factory=list)
    work_dir: str | None = None
    compose_project: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # --- Submission state (mutable) ---
    # 提交状态（可变）。当前默认不读取题目 Flag，不自动判题。
    solved: bool = False
    hint_viewed: bool = False
    hint_penalty: float = 0.0
    submission_count: int = 0
    score: float = 0.0

    # [5] public() strips sensitive fields before sending to the client
    # public() 在发送给客户端前移除敏感字段
    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "task_type": self.task_type,
            "difficulty": self.difficulty,
            "dataset_id": self.dataset_id,
            "tags": self.tags,
            "has_hint": self.hint is not None,
            "judge_mode": self.judge_mode,
            "status": self.status.value,
            "target_url": self.target_url,
            "ports": self.ports,
            "solved": self.solved,
            "hint_viewed": self.hint_viewed,
            "hint_penalty": self.hint_penalty,
            "submission_count": self.submission_count,
            "score": self.score,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
