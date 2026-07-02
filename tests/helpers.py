from __future__ import annotations

from pathlib import Path
from typing import Any

from droplet.models import Challenge

DEFAULT_API_TOKEN = "droplet_dev_admin"


def auth_headers(token: str = DEFAULT_API_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_compose_template(
    template: Path,
    *,
    image: str = "nginx:alpine",
    port_mapping: str = "8080:80",
) -> Path:
    template.mkdir(parents=True, exist_ok=True)
    compose_path = template / "docker-compose.yml"
    compose_path.write_text(
        f"""services:
  web:
    image: {image}
    ports:
      - "{port_mapping}"
""",
        encoding="utf-8",
    )
    return compose_path


def make_challenge(
    template: Path | None = None,
    challenge_id: str = "test-001",
    **overrides: Any,
) -> Challenge:
    if "id" in overrides:
        challenge_id = str(overrides.pop("id"))

    root = Path(overrides.pop("root", template or "/tmp/droplet-test-template"))
    compose_path = Path(overrides.pop("compose_path", root / "docker-compose.yml"))
    if template is not None and not compose_path.exists():
        compose_path = write_compose_template(template)

    defaults: dict[str, Any] = {
        "id": challenge_id,
        "title": challenge_id.title(),
        "description": "Test challenge",
        "category": "web",
        "task_type": "web_ctf_online",
        "difficulty": "easy",
        "tags": ["test"],
        "root": str(root),
        "compose_path": str(compose_path),
        "expose": [{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
    }
    defaults.update(overrides)
    return Challenge(**defaults)
