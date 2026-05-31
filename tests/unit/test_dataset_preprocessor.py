from __future__ import annotations

import json
from pathlib import Path

from datasets.preprocessor.__main__ import main as preprocessor_main


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

    assert (
        preprocessor_main(
            [
                "single",
                "--raw-path",
                str(raw),
                "--output-dir",
                str(output),
                "--challenge-id",
                "RAW-001",
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    challenge = output / "challenges" / "RAW-001"
    assert result["challenge_id"] == "RAW-001"
    assert (challenge / "benchmark.json").exists()
    assert (challenge / "docker-compose.yml").exists()
    assert (challenge / ".env").read_text(encoding="utf-8").startswith("FLAG=flag{")
    assert (challenge / "app" / "Dockerfile").exists()


def test_public_metadata_does_not_include_runtime_secrets(tmp_path: Path) -> None:
    raw = tmp_path / "raw-web"
    output = tmp_path / "draft-dataset"
    _write_raw_challenge(raw)

    # Use CLI to generate draft
    assert (
        preprocessor_main(
            [
                "single",
                "--raw-path",
                str(raw),
                "--output-dir",
                str(output),
                "--challenge-id",
                "RAW-002",
            ]
        )
        == 0
    )

    challenge = output / "challenges" / "RAW-002"
    public_metadata = "\n".join(
        [
            (challenge / "benchmark.json").read_text(encoding="utf-8"),
            (challenge / "docker-compose.yml").read_text(encoding="utf-8"),
        ]
    )
    assert "flag{REAL_RUNTIME_SECRET}" not in public_metadata
    assert "flag{DO_NOT_LEAK}" not in public_metadata
    assert "super-secret-token" not in public_metadata
