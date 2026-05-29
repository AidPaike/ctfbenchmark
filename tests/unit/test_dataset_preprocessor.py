from __future__ import annotations

import json
from pathlib import Path

import yaml

from datasets.preprocessor.cli import main as preprocessor_main
from datasets.preprocessor.generator import generate_draft


def _write_raw_challenge(raw: Path) -> None:
    (raw / "app").mkdir(parents=True)
    (raw / "README.md").write_text(
        "# Raw challenge\n\nThe deployment secret is flag{DO_NOT_LEAK}.\n",
        encoding="utf-8",
    )
    (raw / ".env").write_text(
        "FLAG=flag{REAL_RUNTIME_SECRET}\nAPI_TOKEN=super-secret-token\n",
        encoding="utf-8",
    )
    (raw / "docker-compose.yml").write_text(
        """
services:
  web:
    build:
      context: ./app
    env_file:
      - .env
    ports:
      - "8080:80"
""".lstrip(),
        encoding="utf-8",
    )
    (raw / "app" / "Dockerfile").write_text(
        "FROM nginx:alpine\nCOPY index.html /usr/share/nginx/html/index.html\n",
        encoding="utf-8",
    )
    (raw / "app" / "index.html").write_text("hello\n", encoding="utf-8")


def test_preprocessor_cli_generates_xbow_like_draft(tmp_path: Path, capsys) -> None:
    raw = tmp_path / "raw-web"
    output = tmp_path / "draft-dataset"
    _write_raw_challenge(raw)

    assert preprocessor_main(
        [
            "--raw-path",
            str(raw),
            "--output-dir",
            str(output),
            "--challenge-id",
            "RAW-001",
        ]
    ) == 0

    result = json.loads(capsys.readouterr().out)
    challenge = output / "challenges" / "RAW-001"
    assert result["challenge_id"] == "RAW-001"
    assert result["needs_review"] is True
    assert (output / "droplet.yaml").exists()
    assert (challenge / "benchmark.json").exists()
    assert (challenge / "benchmark.yaml").exists()
    assert (challenge / "README.md").exists()
    assert (challenge / "docker-compose.yml").exists()
    assert (challenge / ".env").read_text(encoding="utf-8").startswith("FLAG=flag{")
    assert (challenge / "_raw" / "README.md").exists()
    assert (challenge / "app" / "Dockerfile").exists()

    droplet = yaml.safe_load((output / "droplet.yaml").read_text(encoding="utf-8"))
    assert droplet["auto_discover"][0]["type"] == "xbow"
    assert droplet["auto_discover"][0]["path"] == "challenges"


def test_public_metadata_does_not_include_runtime_secrets(tmp_path: Path) -> None:
    raw = tmp_path / "raw-web"
    output = tmp_path / "draft-dataset"
    _write_raw_challenge(raw)

    generate_draft(raw, output, challenge_id="RAW-002")

    challenge = output / "challenges" / "RAW-002"
    public_metadata = "\n".join(
        [
            (output / "droplet.yaml").read_text(encoding="utf-8"),
            (challenge / "benchmark.json").read_text(encoding="utf-8"),
            (challenge / "benchmark.yaml").read_text(encoding="utf-8"),
            (challenge / "README.md").read_text(encoding="utf-8"),
        ]
    )
    assert "flag{REAL_RUNTIME_SECRET}" not in public_metadata
    assert "flag{DO_NOT_LEAK}" not in public_metadata
    assert "super-secret-token" not in public_metadata


def test_no_llm_config_still_generates_needs_review_scaffold(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATASET_PREPROCESSOR_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DATASET_PREPROCESSOR_LLM_MODEL", raising=False)
    monkeypatch.delenv("DATASET_PREPROCESSOR_LLM_API_KEY_ENV", raising=False)
    monkeypatch.delenv("DATASET_PREPROCESSOR_LLM_BASE_URL", raising=False)
    raw = tmp_path / "raw-no-compose"
    raw.mkdir()
    (raw / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    output = tmp_path / "draft-dataset"

    result = generate_draft(raw, output)

    challenge = output / "challenges" / "RAW-NO-COMPOSE"
    metadata = json.loads((challenge / "benchmark.json").read_text(encoding="utf-8"))
    notes = json.loads((challenge / "preprocess_notes.json").read_text(encoding="utf-8"))
    assert result.needs_review is True
    assert metadata["needs_review"] is True
    assert "needs_review" in metadata["tags"]
    assert notes["llm"]["provider"] is None
    assert notes["llm"]["has_api_key"] is False
    assert (challenge / "docker-compose.yml").read_text(encoding="utf-8") == "services: {}\n"
