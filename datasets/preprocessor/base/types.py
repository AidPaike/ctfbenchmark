"""Shared data containers for the preprocessor framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChallengeMetadata:
    """Public metadata extracted from a raw challenge.

    Subclasses return this from ``extract_metadata``. All fields are *public* —
    flags, secrets, and internal paths must never appear here.
    """

    name: str
    description: str
    difficulty: int = 2  # 1=easy, 2=medium, 3=hard
    tags: list[str] = field(default_factory=list)
    hint: str | None = None
    win_condition: str = "flag"


@dataclass
class ProcessResult:
    """Result of processing a single challenge."""

    challenge_id: str
    output_dir: Path
    metadata: ChallengeMetadata
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchResult:
    """Result of processing an entire dataset."""

    dataset_type: str
    dataset_root: Path
    results: list[ProcessResult] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> int:
        return len(self.results)

    @property
    def failed(self) -> int:
        return len(self.errors)

    def summary(self) -> str:
        lines = [f"[{self.dataset_type}] {self.ok} succeeded, {self.failed} failed"]
        for r in self.results:
            warns = f"  ({len(r.warnings)} warnings)" if r.warnings else ""
            lines.append(f"  ✓ {r.challenge_id}{warns}")
        for e in self.errors:
            lines.append(f"  ✗ {e['challenge_id']}: {e['error']}")
        return "\n".join(lines)
