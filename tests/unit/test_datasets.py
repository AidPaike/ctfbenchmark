from __future__ import annotations

from pathlib import Path

import pytest

from droplet.datasets import DatasetLoader, _looks_like_dataset


def test_dataset_loader_rejects_unknown_adapter(tmp_path: Path) -> None:
    (tmp_path / "droplet.yaml").write_text(
        "auto_discover:\n  - type: unknown\n    path: challenges\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported dataset adapter"):
        DatasetLoader().load(tmp_path, infer_expose=lambda _path: [])


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

    loaded = DatasetLoader().load(tmp_path, infer_expose=lambda _path: [])

    assert loaded["xben-999-24"].title == "No Flag Read"
    assert loaded["xben-999-24"].judge_mode == "record_only"
    assert loaded["xben-999-24"].dataset_id == tmp_path.name


# --- Auto-discovery tests (droplet.yaml optional) ---


def _make_challenge(path: Path, challenge_id: str, name: str) -> None:
    """Helper to create a minimal challenge directory."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "benchmark.json").write_text(
        f'{{"id":"{challenge_id}","name":"{name}","description":"test","level":1}}',
        encoding="utf-8",
    )
    (path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")


def test_auto_discover_single_dataset_without_droplet_yaml(tmp_path: Path) -> None:
    """droplet.yaml missing + challenges/ present → auto-discovers with xbow defaults."""
    _make_challenge(tmp_path / "challenges" / "AUTO-001", "AUTO-001", "Auto Challenge")

    loaded = DatasetLoader().load(tmp_path, infer_expose=lambda _path: [])

    assert "auto-001" in loaded
    assert loaded["auto-001"].title == "Auto Challenge"
    assert loaded["auto-001"].category == "web"
    assert loaded["auto-001"].dataset_id == tmp_path.name


def test_auto_discover_empty_dir_returns_empty(tmp_path: Path) -> None:
    """droplet.yaml missing + no challenges/ → returns empty dict, no crash."""
    loaded = DatasetLoader().load(tmp_path, infer_expose=lambda _path: [])
    assert loaded == {}


def test_auto_discover_multi_dataset_parent(tmp_path: Path) -> None:
    """Parent dir with two child datasets (no droplet.yaml) → discovers both."""
    _make_challenge(tmp_path / "suite-a" / "challenges" / "A-001", "A-001", "Suite A Challenge")
    _make_challenge(tmp_path / "suite-b" / "challenges" / "B-001", "B-001", "Suite B Challenge")

    loaded = DatasetLoader().load(tmp_path, infer_expose=lambda _path: [])

    assert "a-001" in loaded
    assert "b-001" in loaded
    assert loaded["a-001"].dataset_id == "suite-a"
    assert loaded["b-001"].dataset_id == "suite-b"


def test_auto_discover_mixed_children(tmp_path: Path) -> None:
    """Child with droplet.yaml + child without → both loaded correctly."""
    # Child A: has droplet.yaml
    child_a = tmp_path / "suite-a"
    _make_challenge(child_a / "challenges" / "A-001", "A-001", "Configured")
    (child_a / "droplet.yaml").write_text(
        "auto_discover:\n  - type: xbow\n    path: challenges\n    category: web\n",
        encoding="utf-8",
    )

    # Child B: no droplet.yaml
    _make_challenge(tmp_path / "suite-b" / "challenges" / "B-001", "B-001", "Auto-discovered")

    loaded = DatasetLoader().load(tmp_path, infer_expose=lambda _path: [])

    assert "a-001" in loaded
    assert "b-001" in loaded
    assert loaded["a-001"].title == "Configured"
    assert loaded["b-001"].title == "Auto-discovered"


def test_looks_like_dataset_helper(tmp_path: Path) -> None:
    """_looks_like_dataset correctly identifies dataset directories."""
    assert not _looks_like_dataset(tmp_path)

    (tmp_path / "challenges").mkdir()
    assert not _looks_like_dataset(tmp_path)

    _make_challenge(tmp_path / "challenges" / "X-001", "X-001", "X")
    assert _looks_like_dataset(tmp_path)
