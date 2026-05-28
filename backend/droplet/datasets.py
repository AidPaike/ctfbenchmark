from __future__ import annotations

import json
import re
import shlex
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

import yaml

from droplet.models import Challenge


# [1] Type aliases make the function signatures self-documenting
# 类型别名让函数签名自我文档化
ReadFlag = Callable[[Path], str]
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
        read_flag: ReadFlag,
        infer_expose: InferExpose,
    ) -> Iterable[Challenge]:
        ...


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
        read_flag: ReadFlag,
        infer_expose: InferExpose,
    ) -> dict[str, Challenge]:
        manifest = yaml.safe_load((dataset_root / "droplet.yaml").read_text(encoding="utf-8")) or {}
        loaded: dict[str, Challenge] = {}
        for item in manifest.get("auto_discover", []):
            dataset_type = str(item.get("type") or "").strip()
            adapter = self.adapters.get(dataset_type)
            if adapter is None:
                raise ValueError(f"Unsupported dataset adapter: {dataset_type}")
            for challenge in adapter.discover(
                dataset_root,
                item,
                read_flag=read_flag,
                infer_expose=infer_expose,
            ):
                loaded[challenge.id] = challenge
        return loaded


# [4] XbowDatasetAdapter scans public metadata and docker-compose.yml only.
# XbowDatasetAdapter 只扫描公开元数据和 docker-compose.yml。
class XbowDatasetAdapter:
    dataset_type = "xbow"

    def discover(
        self,
        dataset_root: Path,
        config: dict[str, Any],
        *,
        read_flag: ReadFlag,
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
            # Prefer candidates with .env; fallback to lexicographic path order.
            # 优先选择有 .env 的候选；否则按字典序路径排序。
            directory, meta = sorted(
                candidates,
                key=lambda item: (not (item[0] / ".env").exists(), str(item[0])),
            )[0]
            env_path = directory / ".env"
            if not env_path.exists():
                continue
            readme = directory / "README.md"
            yield Challenge(
                id=original_id.lower(),
                title=str(meta.get("name") or original_id),
                description=_public_description(readme, str(meta.get("description") or "")),
                category=config.get("category") or "web",
                task_type=config.get("task_type") or "web_ctf_online",
                difficulty={1: "easy", 2: "medium", 3: "hard"}.get(
                    int(meta.get("level") or 2),
                    "medium",
                ),
                tags=[str(tag) for tag in meta.get("tags", [])],
                hint=str(h) if (h := meta.get("hint")) else None,
                expected_flag=read_flag(env_path),
                root=str(directory),
                compose_path=str(directory / "docker-compose.yml"),
                env_path=str(env_path),
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


# [8] Read FLAG from .env file using shlex so values with spaces or quotes are handled correctly
# 使用 shlex 从 .env 文件读取 FLAG，以便正确处理带空格或引号的值
def read_env_flag(env_path: Path) -> str:
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "FLAG":
            # shlex.split handles quoted values like "flag{hello world}"
            # shlex.split 处理带引号的值，如 "flag{hello world}"
            parsed = shlex.split(value.strip())
            return parsed[0] if parsed else value.strip()
    return ""
