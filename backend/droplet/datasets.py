from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

import yaml

from droplet.models import Challenge

logger = logging.getLogger(__name__)


# [1] Type aliases make the function signatures self-documenting
# 类型别名让函数签名自我文档化
InferExpose = Callable[[Path], list[dict[str, Any]]]


# [2] Protocol = structural subtyping; no inheritance required
# Protocol = 结构性子类型；不需要显式继承
class DatasetAdapter(Protocol):
    dataset_type: str

    def discover(
        self,
        dataset_root: Path,
        config: dict[str, Any],
        *,
        infer_expose: InferExpose,
    ) -> Iterable[Challenge]: ...


# [3] DatasetLoader registers adapters in a dict keyed by dataset_type.
# Adding a new format only requires a new adapter class.
# DatasetLoader 用 dataset_type 为键将适配器注册到字典中。
# 添加新格式只需要一个新的适配器类。
class DatasetLoader:
    """Load challenge metadata through pluggable dataset adapters."""

    def __init__(self, adapters: Iterable[DatasetAdapter] | None = None) -> None:
        selected = list(adapters or [XbowDatasetAdapter()])
        self.adapters = {adapter.dataset_type: adapter for adapter in selected}

    def load(
        self,
        dataset_root: Path,
        *,
        infer_expose: InferExpose,
        config_path: Path | None = None,
    ) -> dict[str, Challenge]:
        # Config lookup order:
        # 1. Explicit config_path parameter
        # 2. {dataset_root}/../droplet.yaml (project root)
        # 3. {dataset_root}/droplet.yaml (legacy)
        # 4. Auto-discover
        candidates = []
        if config_path is not None:
            candidates.append(config_path)
        candidates.append(dataset_root.parent / "droplet.yaml")
        candidates.append(dataset_root / "droplet.yaml")

        for path in candidates:
            if path.exists():
                return self._load_from_manifest(dataset_root, path, infer_expose=infer_expose)
        return self._auto_discover(dataset_root, infer_expose=infer_expose)

    def _load_from_manifest(
        self,
        dataset_root: Path,
        manifest_path: Path,
        *,
        infer_expose: InferExpose,
    ) -> dict[str, Challenge]:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        config_dir = manifest_path.parent

        # schema_version: 2 — simple path list
        if manifest.get("schema_version") == 2 and "datasets" in manifest:
            return self._load_simple_paths(
                manifest["datasets"], config_dir, infer_expose=infer_expose
            )

        # schema_version: 1 (or legacy) — auto_discover with full config
        loaded: dict[str, Challenge] = {}
        for item in manifest.get("auto_discover", []):
            dataset_type = str(item.get("type") or "").strip()
            adapter = self.adapters.get(dataset_type)
            if adapter is None:
                raise ValueError(f"Unsupported dataset adapter: {dataset_type}")
            for challenge in adapter.discover(
                dataset_root,
                item,
                infer_expose=infer_expose,
            ):
                loaded[challenge.id] = challenge
        return loaded

    def _load_simple_paths(
        self,
        paths: list[str],
        config_dir: Path,
        *,
        infer_expose: InferExpose,
    ) -> dict[str, Challenge]:
        """Load datasets from a simple list of directory paths.

        Each path can be:
        - A directory directly containing challenge subdirs (with benchmark.json)
        - A directory containing a challenges/ subdirectory

        Paths are resolved relative to the config file's directory.
        """
        loaded: dict[str, Challenge] = {}
        adapter = self.adapters.get("xbow")
        if adapter is None:
            raise ValueError("No 'xbow' registered for simple path discovery")

        for raw_path in paths:
            resolved = (config_dir / raw_path).resolve()
            if not resolved.exists():
                logger.warning(f"Dataset path does not exist: {resolved}")
                continue

            # Determine if resolved is a challenge dir itself or a parent
            if _is_challenge_dir(resolved):
                # resolved directly contains challenge subdirs
                dataset_id = resolved.parent.name
                config: dict[str, Any] = {
                    "type": "xbow",
                    "path": resolved.name,
                    "dataset_id": dataset_id,
                    "category": "web",
                    "task_type": "web_ctf_online",
                }
                for challenge in adapter.discover(
                    resolved.parent, config, infer_expose=infer_expose
                ):
                    loaded[challenge.id] = challenge
            else:
                # resolved is a parent; look for challenges/ subdir
                sub_path = _find_challenge_subdir(resolved)
                if sub_path is None:
                    logger.warning(f"No challenges found in: {resolved}")
                    continue
                dataset_id = resolved.name
                config = {
                    "type": "xbow",
                    "path": sub_path,
                    "dataset_id": dataset_id,
                    "category": "web",
                    "task_type": "web_ctf_online",
                }
                for challenge in adapter.discover(resolved, config, infer_expose=infer_expose):
                    loaded[challenge.id] = challenge
        return loaded

    def _auto_discover(
        self,
        dataset_root: Path,
        *,
        infer_expose: InferExpose,
    ) -> dict[str, Challenge]:
        """Auto-discover challenges when droplet.yaml is missing.

        Two modes:
        1. Single-dataset: {root}/challenges/ has benchmark.json subdirs → treat root as xbow dataset
        2. Multi-dataset: scan root's subdirectories, each may have droplet.yaml or challenges/
        """
        # Mode 1: root itself looks like a dataset
        if _looks_like_dataset(dataset_root):
            return self._discover_single(dataset_root, infer_expose=infer_expose)

        # Mode 2: scan child directories
        loaded: dict[str, Challenge] = {}
        for child in sorted(dataset_root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            child_yaml = child / "droplet.yaml"
            if child_yaml.exists():
                loaded.update(
                    self._load_from_manifest(child, child_yaml, infer_expose=infer_expose)
                )
            elif _looks_like_dataset(child):
                loaded.update(self._discover_single(child, infer_expose=infer_expose))
        return loaded

    def _discover_single(
        self,
        dataset_root: Path,
        *,
        infer_expose: InferExpose,
    ) -> dict[str, Challenge]:
        """Discover challenges in a single dataset directory using xbow adapter defaults."""
        adapter = self.adapters.get("xbow")
        if adapter is None:
            raise ValueError("No 'xbow' adapter registered for auto-discovery")
        # Auto-detect the subdirectory containing challenge dirs
        sub_path = _find_challenge_subdir(dataset_root)
        if sub_path is None:
            return {}
        config: dict[str, Any] = {
            "type": "xbow",
            "path": sub_path,
            "dataset_id": dataset_root.name,
            "category": "web",
            "task_type": "web_ctf_online",
        }
        loaded: dict[str, Challenge] = {}
        for challenge in adapter.discover(dataset_root, config, infer_expose=infer_expose):
            loaded[challenge.id] = challenge
        return loaded


def _is_challenge_dir(path: Path) -> bool:
    """Check if a directory directly contains challenge subdirs (with benchmark.json)."""
    try:
        return any(
            (child / "benchmark.json").exists() for child in path.iterdir() if child.is_dir()
        )
    except (PermissionError, OSError):
        return False


def _looks_like_dataset(path: Path) -> bool:
    """Check if a directory is a single dataset.

    A single dataset has a direct child directory whose immediate subdirectories
    contain benchmark.json. E.g.:
        path/challenges/XBEN-001/benchmark.json  → True (challenges is the challenge dir)

    A parent of multiple datasets has children that are themselves datasets:
        path/demo-xbow/challenges/XBEN-001/benchmark.json  → False
    """
    for child in sorted(path.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        # Check if this child directly contains challenge dirs (have benchmark.json)
        has_direct_challenges = any(
            (grandchild / "benchmark.json").exists()
            for grandchild in child.iterdir()
            if grandchild.is_dir()
        )
        if has_direct_challenges:
            return True
    return False


def _find_challenge_subdir(path: Path) -> str | None:
    """Find the first child directory that directly contains challenge subdirs."""
    for child in sorted(path.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        has_direct_challenges = any(
            (grandchild / "benchmark.json").exists()
            for grandchild in child.iterdir()
            if grandchild.is_dir()
        )
        if has_direct_challenges:
            return child.name
    return None


# [4] XbowDatasetAdapter scans public metadata and docker-compose.yml only.
# XbowDatasetAdapter 只扫描公开元数据和 docker-compose.yml。
class XbowDatasetAdapter:
    dataset_type = "xbow"

    def discover(
        self,
        dataset_root: Path,
        config: dict[str, Any],
        *,
        infer_expose: InferExpose,
    ) -> Iterable[Challenge]:
        scan_root = dataset_root / config.get("path", "challenges")
        # [5] Group by id first so we can deduplicate multiple versions
        # 先按 id 分组以便对多个版本去重
        grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
        for benchmark_path in sorted(scan_root.rglob("benchmark.json")):
            directory = benchmark_path.parent
            if not (directory / "docker-compose.yml").exists():
                continue
            meta = json.loads(benchmark_path.read_text(encoding="utf-8"))
            original_id = str(meta.get("id") or directory.name)
            grouped[original_id].append((directory, meta))

        for original_id, candidates in sorted(grouped.items()):
            # Pick a stable path without inspecting .env or other secret-bearing files.
            # 选择稳定路径，不检查 .env 或任何可能承载 secret 的文件。
            directory, meta = sorted(candidates, key=lambda item: str(item[0]))[0]
            readme = directory / "README.md"
            yield Challenge(
                id=original_id.lower(),
                title=str(meta.get("name") or original_id),
                description=_public_description(readme, str(meta.get("description") or "")),
                category=config.get("category") or "web",
                task_type=config.get("task_type") or "web_ctf_online",
                dataset_id=str(config.get("dataset_id") or dataset_root.name),
                difficulty={1: "easy", 2: "medium", 3: "hard"}.get(
                    int(meta.get("level") or 2),
                    "medium",
                ),
                tags=[str(tag) for tag in (meta.get("tags") or [])],
                hint=str(h) if (h := meta.get("hint")) else None,
                judge_mode=str(config.get("judge_mode") or "record_only"),
                root=str(directory),
                compose_path=str(directory / "docker-compose.yml"),
                expose=infer_expose(directory / "docker-compose.yml"),
            )


# [7] Strip build instructions and canary strings that should not be public
# 移除构建说明和金丝雀字符串等不应公开的内容
def _public_description(readme: Path, fallback: str) -> str:
    if not readme.exists():
        return fallback.strip()

    text = readme.read_text(encoding="utf-8")
    for marker in ("\n## Build instructions", "\n## Canary string"):
        if marker in text:
            text = text.split(marker, 1)[0]

    match = re.search(r"### Description\s*\n(.*?)(?=\n#{1,3} |\n*$)", text, re.DOTALL)
    if match:
        desc = match.group(1).strip()
        if desc:
            return desc

    lines = [line for line in text.splitlines() if not line.strip().startswith("#")]
    return "\n".join(lines).strip() or fallback.strip()
