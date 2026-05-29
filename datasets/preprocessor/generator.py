from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .agent import AgentRequest, AgentSuggestion, DraftAgent, LLMAssistedAgent, LLMConfig, ScaffoldAgent


COMPOSE_NAMES = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
PUBLIC_ROOT_NAMES = {
    "benchmark.json",
    "benchmark.yaml",
    "README.md",
    "droplet.yaml",
    "preprocess_notes.json",
    "llm_request.json",
    "_raw",
}
SENSITIVE_NAME_RE = re.compile(
    r"(^\.env$|flag|secret|password|passwd|token|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(flag\{[^}\n]{1,160}\}|"
    r"[a-z0-9_.-]*(flag|secret|password|token|api[_-]?key)\s*[:=]\s*[^,\s`\"']{0,160})"
)


@dataclass(frozen=True)
class PreprocessResult:
    dataset_root: Path
    challenge_dir: Path
    challenge_id: str
    needs_review: bool
    compose_strategy: str
    sensitive_paths: list[str]


def generate_draft(
    raw_path: Path | str,
    output_dir: Path | str,
    *,
    challenge_id: str | None = None,
    dataset_id: str | None = None,
    category: str = "web",
    task_type: str = "web_ctf_online",
    overwrite: bool = False,
    llm_config: LLMConfig | None = None,
    agent: DraftAgent | None = None,
) -> PreprocessResult:
    """Convert a raw challenge directory into a Droplet/XBOW-like draft dataset."""

    raw = Path(raw_path).expanduser().resolve()
    if not raw.is_dir():
        raise ValueError(f"raw challenge path is not a directory: {raw}")

    dataset_root = Path(output_dir).expanduser().resolve()
    dataset_name = dataset_id or _slug(dataset_root.name or "draft-dataset")
    normalized_challenge_id = _challenge_id(challenge_id or raw.name)
    challenge_dir = dataset_root / "challenges" / normalized_challenge_id
    if challenge_dir.exists():
        if not overwrite:
            raise FileExistsError(f"challenge draft already exists: {challenge_dir}")
        shutil.rmtree(challenge_dir)

    challenge_dir.mkdir(parents=True, exist_ok=True)

    inventory = _inventory(raw)
    sensitive_paths = _find_sensitive_paths(raw)
    compose_source = _find_compose(raw)
    raw_copy_root = challenge_dir / "_raw"
    shutil.copytree(raw, raw_copy_root, symlinks=True)

    compose_strategy = _prepare_runtime_files(raw, challenge_dir, compose_source)
    _ensure_env_file(raw, compose_source.parent if compose_source else raw, challenge_dir)

    request = AgentRequest(
        raw_path=raw,
        challenge_id=normalized_challenge_id,
        inventory=inventory,
        sensitive_paths=sensitive_paths,
    )
    selected_agent = agent or LLMAssistedAgent(llm_config or LLMConfig(), fallback=ScaffoldAgent())
    suggestion = _sanitize_suggestion(selected_agent.suggest(request))

    _write_droplet_yaml(dataset_root, dataset_name, category, task_type)
    _write_benchmark_json(challenge_dir, normalized_challenge_id, suggestion)
    _write_benchmark_yaml(challenge_dir, normalized_challenge_id, suggestion)
    _write_readme(
        challenge_dir,
        normalized_challenge_id,
        suggestion,
        compose_strategy=compose_strategy,
        sensitive_paths=sensitive_paths,
    )
    _write_notes(
        challenge_dir,
        raw,
        normalized_challenge_id,
        inventory,
        sensitive_paths,
        compose_source,
        compose_strategy,
        suggestion,
        llm_config or LLMConfig(),
    )

    return PreprocessResult(
        dataset_root=dataset_root,
        challenge_dir=challenge_dir,
        challenge_id=normalized_challenge_id,
        needs_review=suggestion.needs_review,
        compose_strategy=compose_strategy,
        sensitive_paths=sensitive_paths,
    )


def _challenge_id(value: str) -> str:
    slug = _slug(value).upper()
    return slug or "DRAFT-CHALLENGE"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-")
    return cleaned.lower()


def _inventory(raw: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(raw.rglob("*")):
        rel = path.relative_to(raw).as_posix()
        if path.is_dir():
            continue
        try:
            size = path.lstat().st_size
        except OSError:
            size = None
        entries.append({"path": rel, "size": size})
    return entries


def _find_compose(raw: Path) -> Path | None:
    candidates = [path for path in raw.rglob("*") if path.is_file() and path.name in COMPOSE_NAMES]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (path.parent != raw, len(path.parts), path.as_posix()))[0]


def _find_sensitive_paths(raw: Path) -> list[str]:
    sensitive: set[str] = set()
    for path in sorted(raw.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(raw).as_posix()
        if SENSITIVE_NAME_RE.search(path.name):
            sensitive.add(rel)
            continue
        if _text_file_contains_sensitive_token(path):
            sensitive.add(rel)
    return sorted(sensitive)


def _text_file_contains_sensitive_token(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) > 1024 * 1024 or b"\x00" in data[:4096]:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return bool(SENSITIVE_TEXT_RE.search(text))


def _sanitize_suggestion(suggestion: AgentSuggestion) -> AgentSuggestion:
    return AgentSuggestion(
        title=_redact_public_text(suggestion.title),
        description=_redact_public_text(suggestion.description),
        difficulty_level=suggestion.difficulty_level,
        tags=[_redact_public_text(tag) for tag in suggestion.tags],
        needs_review=True,
        notes=[_redact_public_text(note) for note in suggestion.notes],
    )


def _redact_public_text(value: str) -> str:
    return SENSITIVE_TEXT_RE.sub("[REDACTED]", value)


def _prepare_runtime_files(raw: Path, challenge_dir: Path, compose_source: Path | None) -> str:
    if compose_source is None:
        (challenge_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        return (
            "No docker-compose file was detected. A placeholder docker-compose.yml was "
            "created and must be reviewed before runtime use."
        )

    runtime_root = compose_source.parent
    for item in sorted(runtime_root.iterdir(), key=lambda path: path.name):
        if item.name in PUBLIC_ROOT_NAMES:
            continue
        destination = challenge_dir / item.name
        if item.is_dir():
            shutil.copytree(item, destination, symlinks=True)
        elif item.is_symlink():
            destination.symlink_to(item.readlink())
        else:
            shutil.copy2(item, destination, follow_symlinks=False)

    if compose_source.name != "docker-compose.yml":
        shutil.copy2(compose_source, challenge_dir / "docker-compose.yml", follow_symlinks=False)

    rel_parent = runtime_root.relative_to(raw).as_posix() if runtime_root != raw else "."
    return (
        f"Detected {compose_source.name} under raw path '{rel_parent}'. The compose parent "
        "was copied to the draft challenge root so relative build contexts remain intact."
    )


def _ensure_env_file(raw: Path, runtime_root: Path, challenge_dir: Path) -> None:
    destination = challenge_dir / ".env"
    if destination.exists():
        return

    for candidate in (runtime_root / ".env", raw / ".env"):
        if candidate.exists() and candidate.is_file():
            shutil.copy2(candidate, destination, follow_symlinks=False)
            return

    destination.write_text(
        "# Draft placeholder. Replace during review if the challenge expects FLAG.\n"
        "FLAG=REVIEW_REQUIRED\n",
        encoding="utf-8",
    )


def _write_droplet_yaml(dataset_root: Path, dataset_id: str, category: str, task_type: str) -> None:
    data = {
        "schema_version": 1,
        "suite": {
            "id": dataset_id,
            "name": _display_name(dataset_id),
            "version": "draft",
            "license": "review-required",
        },
        "auto_discover": [
            {
                "type": "xbow",
                "path": "challenges",
                "category": category,
                "task_type": task_type,
                "default_max_submissions": 20,
            }
        ],
    }
    (dataset_root / "droplet.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_benchmark_json(challenge_dir: Path, challenge_id: str, suggestion) -> None:
    data = {
        "id": challenge_id,
        "name": suggestion.title,
        "description": suggestion.description,
        "level": suggestion.difficulty_level,
        "win_condition": "flag",
        "tags": suggestion.tags,
        "needs_review": suggestion.needs_review,
        "preprocessor": {
            "name": "datasets.preprocessor",
            "metadata_policy": "secret-free-public-metadata",
        },
    }
    (challenge_dir / "benchmark.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_benchmark_yaml(challenge_dir: Path, challenge_id: str, suggestion) -> None:
    data = {
        "id": challenge_id,
        "name": suggestion.title,
        "level": suggestion.difficulty_level,
        "tags": suggestion.tags,
        "needs_review": suggestion.needs_review,
        "content": [
            {
                "kind": "description",
                "content_type": "text/markdown",
                "content": suggestion.description,
            }
        ],
        "xbow_dont_bundle_source": True,
    }
    (challenge_dir / "benchmark.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )


def _write_readme(
    challenge_dir: Path,
    challenge_id: str,
    suggestion,
    *,
    compose_strategy: str,
    sensitive_paths: list[str],
) -> None:
    sensitive_note = "None detected by filename/lightweight scan."
    if sensitive_paths:
        sensitive_note = "\n".join(f"- `{path}`" for path in sensitive_paths)

    text = f"""# {suggestion.title}

## Challenge Details

### Description
{suggestion.description}

### Draft Status
- `needs_review`: `{str(suggestion.needs_review).lower()}`
- Review public metadata, exposed ports, health checks, flag injection, and category tags.
- A full copy of the original raw challenge is preserved under `_raw/`.

### Docker Compose Strategy
{compose_strategy}

### Sensitive Runtime Files
The preprocessor never copies flag or secret values into public metadata. Sensitive-looking
paths are kept only as runtime/source files:

{sensitive_note}

### Notes
{_markdown_list(suggestion.notes)}
"""
    (challenge_dir / "README.md").write_text(text, encoding="utf-8")


def _write_notes(
    challenge_dir: Path,
    raw: Path,
    challenge_id: str,
    inventory: list[dict[str, Any]],
    sensitive_paths: list[str],
    compose_source: Path | None,
    compose_strategy: str,
    suggestion,
    llm_config: LLMConfig,
) -> None:
    compose_rel = compose_source.relative_to(raw).as_posix() if compose_source else None
    notes = {
        "challenge_id": challenge_id,
        "raw_path": str(raw),
        "needs_review": suggestion.needs_review,
        "compose_source": compose_rel,
        "compose_strategy": compose_strategy,
        "sensitive_paths": sensitive_paths,
        "llm": llm_config.public_dict(),
        "agent_notes": suggestion.notes,
        "manual_review_checklist": [
            "Verify docker-compose.yml builds and exposes the intended service.",
            "Verify .env and flag files remain runtime-only.",
            "Replace draft description/tags/difficulty with reviewed public metadata.",
            "Run Droplet preflight before merging into a benchmark dataset.",
        ],
        "inventory": inventory,
    }
    (challenge_dir / "preprocess_notes.json").write_text(
        json.dumps(notes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    llm_request = {
        "instruction": (
            "Use the file inventory and notes to propose public challenge metadata. "
            "Do not include flag values, secrets, .env contents, private keys, tokens, "
            "or canary strings in any public output."
        ),
        "challenge_id": challenge_id,
        "inventory": inventory,
        "sensitive_paths": sensitive_paths,
        "current_public_metadata": {
            "name": suggestion.title,
            "description": suggestion.description,
            "level": suggestion.difficulty_level,
            "tags": suggestion.tags,
        },
    }
    (challenge_dir / "llm_request.json").write_text(
        json.dumps(llm_request, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _display_name(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title() or "Draft Dataset"


def _markdown_list(items: list[str]) -> str:
    if not items:
        return "- No agent notes."
    return "\n".join(f"- {item}" for item in items)
