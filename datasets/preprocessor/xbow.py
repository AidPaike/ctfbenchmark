"""XBOW dataset preprocessor.

Handles raw XBOW challenge directories that contain:
- ``benchmark.json`` with public metadata
- ``docker-compose.yml`` for runtime
- Source directories (``app/``, ``mysql/``, etc.)
- ``.env`` with flag injection
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable

from .base import BasePreprocessor, ChallengeMetadata


class XbowPreprocessor(BasePreprocessor):
    """Preprocessor for XBOW-format challenge datasets."""

    @property
    def dataset_type(self) -> str:
        return "xbow"

    def discover(self, raw_path: Path) -> Iterable[tuple[str, Path]]:
        """Scan *raw_path* for directories containing ``benchmark.json``.

        Supports two layouts:
        1. Flat: ``<raw_path>/<challenge>/benchmark.json``
        2. Nested: ``<raw_path>/challenges/<challenge>/benchmark.json``
        """
        # Try flat layout first
        found = False
        for child in sorted(raw_path.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            bm = child / "benchmark.json"
            if bm.exists():
                found = True
                cid = self._id_from_benchmark(bm, child.name)
                yield cid, child

        # If nothing found flat, try one level deeper (challenges/ subdir)
        if not found:
            challenges_dir = raw_path / "challenges"
            if challenges_dir.is_dir():
                for child in sorted(challenges_dir.iterdir()):
                    if not child.is_dir() or child.name.startswith("."):
                        continue
                    bm = child / "benchmark.json"
                    if bm.exists():
                        cid = self._id_from_benchmark(bm, child.name)
                        yield cid, child

    def extract_metadata(self, raw_challenge_path: Path, challenge_id: str) -> ChallengeMetadata:
        """Read ``benchmark.json`` for public metadata."""
        bm_path = raw_challenge_path / "benchmark.json"
        if not bm_path.exists():
            return ChallengeMetadata(
                name=challenge_id,
                description=f"Draft challenge {challenge_id}. Review required.",
                tags=["draft", "needs_review"],
            )

        data = json.loads(bm_path.read_text(encoding="utf-8"))

        # Sanitize description — strip build instructions and canary strings
        description = str(data.get("description") or "")
        description = _strip_sensitive_sections(description)

        return ChallengeMetadata(
            name=str(data.get("name") or challenge_id),
            description=description,
            difficulty=int(data.get("level") or 2),
            tags=[str(t) for t in (data.get("tags") or [])],
            hint=str(h) if (h := data.get("hint")) else None,
            win_condition=str(data.get("win_condition") or "flag"),
        )

    def prepare_runtime(
        self,
        raw_challenge_path: Path,
        output_challenge_dir: Path,
    ) -> str:
        """Copy compose + source directories into the output."""
        compose = self._find_compose(raw_challenge_path)
        if compose is None:
            (output_challenge_dir / "docker-compose.yml").write_text(
                "services: {}\n", encoding="utf-8"
            )
            return (
                "No docker-compose file detected. A placeholder was created — "
                "review before runtime use."
            )

        # Copy everything except known non-runtime files
        skip = {"benchmark.json", "benchmark.yaml", "README.md", "preprocess_notes.json", "llm_request.json"}
        for item in sorted(raw_challenge_path.iterdir()):
            if item.name in skip:
                continue
            dest = output_challenge_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, symlinks=True)
            elif item.is_file() or item.is_symlink():
                shutil.copy2(item, dest, follow_symlinks=False)

        # Ensure compose is named docker-compose.yml
        if compose.name != "docker-compose.yml":
            shutil.copy2(compose, output_challenge_dir / "docker-compose.yml", follow_symlinks=False)

        rel = compose.relative_to(raw_challenge_path).as_posix()
        return (
            f"Detected {compose.name} at '{rel}'. All runtime files were copied "
            "to the draft challenge root."
        )

    def droplet_yaml_config(self, dataset_id: str) -> dict:
        return {
            "category": "web",
            "task_type": "web_ctf_online",
            "default_max_submissions": 20,
        }

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _id_from_benchmark(bm_path: Path, fallback: str) -> str:
        try:
            data = json.loads(bm_path.read_text(encoding="utf-8"))
            return str(data.get("id") or fallback)
        except Exception:
            return fallback

    @staticmethod
    def _find_compose(raw: Path) -> Path | None:
        names = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
        candidates = [p for p in raw.rglob("*") if p.is_file() and p.name in names]
        if not candidates:
            return None
        # Prefer root-level, then shortest path
        return sorted(candidates, key=lambda p: (p.parent != raw, len(p.parts), p.as_posix()))[0]


def _strip_sensitive_sections(text: str) -> str:
    """Remove build instructions and canary strings from description text."""
    for marker in ("\n## Build instructions", "\n## Canary string"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip()
