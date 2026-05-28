from __future__ import annotations

from pathlib import Path

import pytest

from droplet.datasets import DatasetLoader


def test_dataset_loader_rejects_unknown_adapter(tmp_path: Path) -> None:
    (tmp_path / "droplet.yaml").write_text(
        "auto_discover:\n  - type: unknown\n    path: challenges\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported dataset adapter"):
        DatasetLoader().load(tmp_path, infer_expose=lambda _path: [], read_flag=lambda _path: None)


def test_xbow_loader_does_not_require_or_read_env_flag(tmp_path: Path) -> None:
    challenge = tmp_path / "challenges" / "XBEN-999-24"
    challenge.mkdir(parents=True)
    (tmp_path / "droplet.yaml").write_text(
        "auto_discover:\n  - type: xbow\n    path: challenges\n    category: web\n",
        encoding="utf-8",
    )
    (challenge / "benchmark.json").write_text(
        '{"id":"XBEN-999-24","name":"No Flag Read","description":"metadata only","level":1}',
        encoding="utf-8",
    )
    (challenge / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (challenge / ".env").write_text("FLAG=flag{test}\n", encoding="utf-8")

    loaded = DatasetLoader().load(tmp_path, infer_expose=lambda _path: [], read_flag=lambda _path: "")

    assert loaded["xben-999-24"].title == "No Flag Read"
    assert loaded["xben-999-24"].judge_mode == "record_only"
