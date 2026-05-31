"""Abstract base class for dataset preprocessors.

Subclass ``BasePreprocessor`` and implement the four abstract hooks
to support a new dataset source:

- ``dataset_type``: short identifier (e.g. ``"xbow"``, ``"ctfd"``).
- ``discover``: scan a raw directory and yield ``(challenge_id, raw_path)`` pairs.
- ``extract_metadata``: return a ``ChallengeMetadata`` from a raw challenge dir.
- ``prepare_runtime``: copy / generate runtime files (compose, .env, source) into output.

The base class handles everything else: directory scaffolding, droplet.yaml generation,
benchmark.json / benchmark.yaml / README.md writing, and batch orchestration.
"""

from __future__ import annotations

import json
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

import yaml

from .types import BatchResult, ChallengeMetadata, ProcessResult


class BasePreprocessor(ABC):
    """Template-method base for dataset preprocessors.

    Public API: ``process_one`` (single challenge) and ``process_batch``
    (all challenges in a raw dataset directory).
    """

    # -- subclass must define --------------------------------------------------

    @property
    @abstractmethod
    def dataset_type(self) -> str:
        """Short identifier for this dataset type (e.g. ``"xbow"``)."""
        ...

    @abstractmethod
    def discover(self, raw_path: Path) -> Iterable[tuple[str, Path]]:
        """Yield ``(challenge_id, challenge_dir)`` pairs found under *raw_path*."""
        ...

    @abstractmethod
    def extract_metadata(self, raw_challenge_path: Path, challenge_id: str) -> ChallengeMetadata:
        """Extract public metadata from a raw challenge directory.

        Must **never** read or embed flag values, secrets, or private keys.
        """
        ...

    @abstractmethod
    def prepare_runtime(
        self,
        raw_challenge_path: Path,
        output_challenge_dir: Path,
    ) -> str:
        """Copy / generate runtime files into *output_challenge_dir*.

        Must create at least a ``docker-compose.yml`` (even if placeholder).
        Returns a human-readable strategy description.
        """
        ...

    # -- optional hooks --------------------------------------------------------

    def normalize_challenge_id(self, raw_id: str) -> str:
        """Sanitize a raw challenge id into a filesystem-safe uppercase slug."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw_id).strip("-").upper()
        return slug or "DRAFT-CHALLENGE"

    def droplet_yaml_config(self, dataset_id: str) -> dict[str, Any]:
        """Return extra keys merged into ``auto_discover[0]``.

        Base sets ``type``, ``path``, ``category``, ``task_type``.
        Override to add ``default_max_submissions``, custom category, etc.
        """
        return {}

    # -- public API ------------------------------------------------------------

    def process_one(
        self,
        raw_path: Path | str,
        output_dir: Path | str,
        *,
        challenge_id: str | None = None,
        dataset_id: str | None = None,
        overwrite: bool = False,
    ) -> ProcessResult:
        """Process a single raw challenge directory into a Droplet draft."""

        raw = Path(raw_path).expanduser().resolve()
        if not raw.is_dir():
            raise ValueError(f"raw challenge path is not a directory: {raw}")

        out = Path(output_dir).expanduser().resolve()
        cid = self.normalize_challenge_id(challenge_id or raw.name)
        challenge_dir = out / "challenges" / cid

        if challenge_dir.exists():
            if not overwrite:
                raise FileExistsError(f"challenge draft already exists: {challenge_dir}")
            shutil.rmtree(challenge_dir)

        challenge_dir.mkdir(parents=True, exist_ok=True)

        metadata = self.extract_metadata(raw, cid)
        strategy = self.prepare_runtime(raw, challenge_dir)
        self._ensure_env(raw, challenge_dir)

        self._write_benchmark_json(challenge_dir, cid, metadata)
        self._write_benchmark_yaml(challenge_dir, cid, metadata)
        self._write_readme(challenge_dir, cid, metadata, strategy)

        ds_id = dataset_id or out.name
        self._write_droplet_yaml(out, ds_id)

        return ProcessResult(challenge_id=cid, output_dir=challenge_dir, metadata=metadata)

    def process_batch(
        self,
        raw_path: Path | str,
        output_dir: Path | str,
        *,
        dataset_id: str | None = None,
        overwrite: bool = False,
    ) -> BatchResult:
        """Discover and process all challenges under *raw_path*."""

        raw = Path(raw_path).expanduser().resolve()
        out = Path(output_dir).expanduser().resolve()
        ds_id = dataset_id or out.name

        result = BatchResult(dataset_type=self.dataset_type, dataset_root=out)

        for cid, challenge_path in self.discover(raw):
            try:
                r = self.process_one(
                    challenge_path, out,
                    challenge_id=cid, dataset_id=ds_id, overwrite=overwrite,
                )
                result.results.append(r)
            except Exception as exc:
                result.errors.append({"challenge_id": cid, "error": str(exc)})

        return result

    # -- file writers ----------------------------------------------------------

    def _write_droplet_yaml(self, dataset_root: Path, dataset_id: str) -> None:
        extra = self.droplet_yaml_config(dataset_id)
        entry: dict[str, Any] = {
            "type": self.dataset_type,
            "path": "challenges",
            "category": extra.pop("category", "web"),
            "task_type": extra.pop("task_type", "web_ctf_online"),
        }
        entry.update(extra)

        data = {
            "schema_version": 1,
            "suite": {
                "id": dataset_id,
                "name": self._display_name(dataset_id),
                "version": "draft",
                "license": "review-required",
            },
            "auto_discover": [entry],
        }
        (dataset_root / "droplet.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8",
        )

    def _write_benchmark_json(self, challenge_dir: Path, cid: str, meta: ChallengeMetadata) -> None:
        data = {
            "id": cid,
            "name": meta.name,
            "description": meta.description,
            "level": str(meta.difficulty),
            "win_condition": meta.win_condition,
            "tags": meta.tags,
            "needs_review": True,
            "preprocessor": {"name": f"datasets.preprocessor.{self.dataset_type}"},
        }
        (challenge_dir / "benchmark.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )

    def _write_benchmark_yaml(self, challenge_dir: Path, cid: str, meta: ChallengeMetadata) -> None:
        data = {
            "id": cid,
            "name": meta.name,
            "level": meta.difficulty,
            "tags": meta.tags,
            "needs_review": True,
            "content": [
                {
                    "kind": "description",
                    "content_type": "text/markdown",
                    "content": meta.description,
                }
            ],
        }
        (challenge_dir / "benchmark.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8",
        )

    def _write_readme(
        self, challenge_dir: Path, cid: str, meta: ChallengeMetadata, strategy: str,
    ) -> None:
        hint_section = f"\n### Hint\n{meta.hint}\n" if meta.hint else ""
        difficulty_label = {1: "Easy", 2: "Medium", 3: "Hard"}.get(meta.difficulty, "Medium")
        text = f"""# {meta.name}

## Challenge Details

### Description
{meta.description}

### Difficulty
{difficulty_label}
{hint_section}
### Draft Status
- `needs_review`: `true`
- Review public metadata, exposed ports, health checks, flag injection, and category tags.

### Docker Compose Strategy
{strategy}
"""
        (challenge_dir / "README.md").write_text(text, encoding="utf-8")

    def _ensure_env(self, raw: Path, challenge_dir: Path) -> None:
        dest = challenge_dir / ".env"
        if dest.exists():
            return
        for candidate in (raw / ".env",):
            if candidate.exists() and candidate.is_file():
                shutil.copy2(candidate, dest, follow_symlinks=False)
                return
        dest.write_text(
            "# Draft placeholder. Replace during review if the challenge expects FLAG.\n"
            "FLAG=REVIEW_REQUIRED\n",
            encoding="utf-8",
        )

    @staticmethod
    def _display_name(slug: str) -> str:
        return re.sub(r"[-_]+", " ", slug).strip().title() or "Draft Dataset"
