from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMConfig:
    """Public, secret-free configuration for optional LLM-assisted preprocessing."""

    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            provider=os.getenv("DATASET_PREPROCESSOR_LLM_PROVIDER") or None,
            model=os.getenv("DATASET_PREPROCESSOR_LLM_MODEL") or None,
            api_key_env=os.getenv("DATASET_PREPROCESSOR_LLM_API_KEY_ENV") or None,
            base_url=os.getenv("DATASET_PREPROCESSOR_LLM_BASE_URL") or None,
        )

    @property
    def requested(self) -> bool:
        return bool(self.provider or self.model or self.api_key_env or self.base_url)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_env and os.getenv(self.api_key_env))

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "has_api_key": self.has_api_key,
        }


@dataclass(frozen=True)
class AgentSuggestion:
    """Metadata proposal from a rule-based or LLM-assisted agent."""

    title: str
    description: str
    difficulty_level: int = 2
    tags: list[str] = field(default_factory=list)
    needs_review: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentRequest:
    raw_path: Path
    challenge_id: str
    inventory: Sequence[dict[str, Any]]
    sensitive_paths: Sequence[str]


class DraftAgent(Protocol):
    def suggest(self, request: AgentRequest) -> AgentSuggestion:
        ...


LLMRunner = Callable[[AgentRequest, LLMConfig], AgentSuggestion]


class ScaffoldAgent:
    """Deterministic fallback that never reads raw challenge secrets into metadata."""

    def suggest(self, request: AgentRequest) -> AgentSuggestion:
        title = _title_from_path(request.raw_path, request.challenge_id)
        tags = sorted({"draft", "needs_review", *_infer_tags(request.inventory)})
        notes = ["No LLM configuration was used; public metadata is a draft scaffold."]
        if request.sensitive_paths:
            notes.append("Sensitive-looking files were preserved only as runtime source files.")
        return AgentSuggestion(
            title=title,
            description=(
                "Draft scaffold generated from a raw challenge. Review the description, "
                "category, tags, exposed ports, health checks, and flag handling before "
                "including this challenge in a benchmark."
            ),
            tags=tags,
            needs_review=True,
            notes=notes,
        )


class LLMAssistedAgent:
    """Optional wrapper for a caller-provided LLM runner.

    The CLI does not ship an API client or read API keys directly. Integrators can pass
    a runner that receives a secret-free request plus an LLMConfig whose API key is
    referenced by environment-variable name only.
    """

    def __init__(
        self,
        config: LLMConfig,
        *,
        runner: LLMRunner | None = None,
        fallback: DraftAgent | None = None,
    ) -> None:
        self.config = config
        self.runner = runner
        self.fallback = fallback or ScaffoldAgent()

    def suggest(self, request: AgentRequest) -> AgentSuggestion:
        if self.config.requested and self.config.has_api_key and self.runner is not None:
            return self.runner(request, self.config)

        suggestion = self.fallback.suggest(request)
        notes = list(suggestion.notes)
        if self.config.requested:
            notes.append(
                "LLM config was provided, but no executable LLM runner is wired into this CLI."
            )
        else:
            notes.append("Set LLM config env vars or pass CLI LLM options to request assistance.")
        return AgentSuggestion(
            title=suggestion.title,
            description=suggestion.description,
            difficulty_level=suggestion.difficulty_level,
            tags=suggestion.tags,
            needs_review=True,
            notes=notes,
        )


def _title_from_path(raw_path: Path, challenge_id: str) -> str:
    name = re.sub(r"[_-]+", " ", raw_path.name).strip()
    if not name:
        name = challenge_id
    return f"{challenge_id} {name.title()}"


def _infer_tags(inventory: Sequence[dict[str, Any]]) -> set[str]:
    text = " ".join(str(item.get("path", "")) for item in inventory).lower()
    tags: set[str] = set()
    for token in ("web", "pwn", "crypto", "forensics", "reverse", "misc"):
        if token in text:
            tags.add(token)
    if "dockerfile" in text or "docker-compose" in text or "compose.yaml" in text:
        tags.add("docker")
    return tags
