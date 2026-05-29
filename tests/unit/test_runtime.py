from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

from droplet.models import Challenge
from droplet import manager as manager_module
from droplet.manager import DropletManager


def _make_challenge(template: Path, challenge_id: str = "demo") -> Challenge:
    template.mkdir(parents=True, exist_ok=True)
    (template / "docker-compose.yml").write_text(
        """services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
""",
        encoding="utf-8",
    )
    return Challenge(
        id=challenge_id,
        title=challenge_id.title(),
        description="Demo challenge",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        root=str(template),
        compose_path=str(template / "docker-compose.yml"),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
    )


def test_start_compose_uses_absolute_compose_file_with_challenge_cwd(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def fake_resolve(self, project, exposed, docker_env):
        return [{**item, "host_port": 34567} for item in exposed]

    monkeypatch.setattr(manager_module.subprocess, "run", fake_run)
    monkeypatch.setattr(DropletManager, "_resolve_ports", fake_resolve)

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    ready_checks = []
    monkeypatch.setattr(manager, "_wait_for_endpoints", lambda endpoints: ready_checks.extend(endpoints))
    challenge = _make_challenge(template)

    work_dir = tmp_path / "work" / "challenges" / "demo"
    result = manager._start_compose(challenge, work_dir)

    command, kwargs = calls[0]
    compose_path = Path(command[command.index("-f") + 1])
    assert compose_path.is_absolute()
    assert compose_path == tmp_path / "work" / "challenges" / "demo" / "docker-compose.yml"
    assert "--wait" not in command
    assert "--build" not in command
    assert Path(kwargs["cwd"]) == tmp_path / "work" / "challenges" / "demo"
    assert result["target_url"] == "http://127.0.0.1:34567"
    assert ready_checks == [{"type": "http", "label": "web", "url": "http://127.0.0.1:34567", "host": "127.0.0.1", "port": 34567, "service": "web"}]


def test_start_compose_injects_docker_proxy_into_runtime_copy_only(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"
    app = template / "app"
    app.mkdir(parents=True)
    (app / "Dockerfile").write_text(
        "FROM python:3.12\nENV HTTP_PROXY=http://old.proxy:7890\nRUN echo ok\n",
        encoding="utf-8",
    )
    (template / "docker-compose.yml").write_text(
        """services:
  web:
    build:
      context: ./app
      args:
        - FLAG
        - HTTP_PROXY=http://old.proxy:7890
    ports:
      - "8080:80"
""",
        encoding="utf-8",
    )

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("DROPLET_DOCKER_PROXY", "192.168.3.67:7890")
    monkeypatch.setenv("DROPLET_DOCKER_NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setattr(DropletManager, "_resolve_ports", lambda _s, _p, exposed, _e: [{**item, "host_port": 34567} for item in exposed])
    monkeypatch.setattr(manager_module.subprocess, "run", fake_run)

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    monkeypatch.setattr(manager, "_wait_for_endpoints", lambda endpoints: None)
    challenge = Challenge(
        id="demo",
        title="Demo",
        description="Demo",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        root=str(template),
        compose_path=str(template / "docker-compose.yml"),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
    )

    work_dir = tmp_path / "work" / "challenges" / "demo"
    manager._start_compose(challenge, work_dir)

    runtime_compose = yaml.safe_load((work_dir / "docker-compose.yml").read_text(encoding="utf-8"))
    runtime_args = runtime_compose["services"]["web"]["build"]["args"]
    assert "FLAG" in runtime_args
    assert "HTTP_PROXY=http://192.168.3.67:7890" in runtime_args
    assert "HTTPS_PROXY=http://192.168.3.67:7890" in runtime_args
    no_proxy_arg = next(arg for arg in runtime_args if arg.startswith("NO_PROXY="))
    assert "localhost" in no_proxy_arg
    assert "127.0.0.1" in no_proxy_arg
    assert "pypi.tuna.tsinghua.edu.cn" in no_proxy_arg
    runtime_dockerfile = (work_dir / "app" / "Dockerfile").read_text(encoding="utf-8")
    assert "http://old.proxy:7890" not in runtime_dockerfile
    assert "192.168.3.67:7890" not in runtime_dockerfile
    assert "http://old.proxy:7890" in (app / "Dockerfile").read_text(encoding="utf-8")
    assert calls[0][1]["env"]["HTTP_PROXY"] == "http://192.168.3.67:7890"


def test_start_compose_can_force_rebuild_with_env_var(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("DROPLET_FORCE_REBUILD", "1")
    monkeypatch.setattr(DropletManager, "_resolve_ports", lambda _s, _p, exposed, _e: [{**item, "host_port": 34567} for item in exposed])
    monkeypatch.setattr(manager_module.subprocess, "run", fake_run)

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    monkeypatch.setattr(manager, "_wait_for_endpoints", lambda endpoints: None)
    challenge = _make_challenge(template)

    manager._start_compose(challenge, tmp_path / "work" / "challenges" / "demo")

    command = calls[0][0]
    assert command[-3:] == ["up", "--build", "-d"]


def test_start_compose_strips_stale_proxy_when_proxy_is_disabled(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"
    app = template / "app"
    app.mkdir(parents=True)
    (app / "Dockerfile").write_text(
        "FROM python:3.12\nENV HTTP_PROXY=http://stale.proxy:7890\nRUN echo ok\n",
        encoding="utf-8",
    )
    (template / "docker-compose.yml").write_text(
        """services:
  web:
    build:
      context: ./app
      args:
        - FLAG
        - HTTP_PROXY=http://stale.proxy:7890
    ports:
      - "8080:80"
""",
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.delenv("DROPLET_DOCKER_PROXY", raising=False)
    monkeypatch.setattr(DropletManager, "_resolve_ports", lambda _s, _p, exposed, _e: [{**item, "host_port": 34567} for item in exposed])
    monkeypatch.setattr(manager_module.subprocess, "run", fake_run)

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    monkeypatch.setattr(manager, "_wait_for_endpoints", lambda endpoints: None)
    challenge = Challenge(
        id="demo",
        title="Demo",
        description="Demo",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        root=str(template),
        compose_path=str(template / "docker-compose.yml"),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
    )

    work_dir = tmp_path / "work" / "challenges" / "demo"
    manager._start_compose(challenge, work_dir)

    runtime_compose = yaml.safe_load((work_dir / "docker-compose.yml").read_text(encoding="utf-8"))
    assert runtime_compose["services"]["web"]["build"]["args"] == ["FLAG"]
    runtime_dockerfile = (work_dir / "app" / "Dockerfile").read_text(encoding="utf-8")
    assert "stale.proxy" not in runtime_dockerfile
    assert "stale.proxy" in (app / "Dockerfile").read_text(encoding="utf-8")


def test_docker_no_proxy_preserves_user_entries_and_adds_platform_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DROPLET_DOCKER_NO_PROXY", "custom.internal,localhost")

    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")

    assert manager.docker_no_proxy == (
        "custom.internal,localhost,127.0.0.1,::1,host.docker.internal,pypi.tuna.tsinghua.edu.cn"
    )


def test_rewrite_ports_uses_zero_host_port_to_avoid_race(tmp_path) -> None:
    """Docker picks the host port directly so there is no TOCTOU window."""
    template = tmp_path / "template"
    template.mkdir(parents=True)
    (template / "docker-compose.yml").write_text(
        """services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
""",
        encoding="utf-8",
    )
    challenge = Challenge(
        id="demo",
        title="Demo",
        description="Demo",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        root=str(template),
        compose_path=str(template / "docker-compose.yml"),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80}],
    )
    manager = DropletManager(dataset_root=tmp_path, work_root=tmp_path / "work")
    work_dir = tmp_path / "work" / "challenges" / "demo"
    work_dir.mkdir(parents=True)
    shutil.copytree(challenge.root, work_dir, dirs_exist_ok=True)
    compose_path = work_dir / "docker-compose.yml"

    exposed = manager._rewrite_ports(compose_path, challenge.expose)

    assert exposed[0]["host_port"] == 0
    runtime = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    assert runtime["services"]["web"]["ports"] == ["0:80"]


def test_query_host_port_parses_docker_compose_port_output(monkeypatch) -> None:
    """_query_host_port extracts the host port from docker compose port output."""
    manager = DropletManager(dataset_root=Path("."), work_root=Path("."))

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="0.0.0.0:54321\n", stderr="")

    monkeypatch.setattr(manager_module.subprocess, "run", fake_run)
    port = manager._query_host_port("test_project", "web", 80, {})

    assert port == 54321
    assert calls[0][-3:] == ["port", "web", "80"]


def test_query_host_port_retries_on_failure_then_succeeds(monkeypatch) -> None:
    """_query_host_port retries when docker compose port returns non-zero."""
    manager = DropletManager(dataset_root=Path("."), work_root=Path("."))
    attempt = [0]

    def fake_run(command, **kwargs):
        attempt[0] += 1
        if attempt[0] < 2:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="error")
        return subprocess.CompletedProcess(command, 0, stdout="0.0.0.0:55555\n", stderr="")

    monkeypatch.setattr(manager_module.subprocess, "run", fake_run)
    port = manager._query_host_port("test_project", "web", 80, {})

    assert port == 55555
    assert attempt[0] == 2


def test_resolve_ports_updates_host_ports_from_docker(monkeypatch) -> None:
    """_resolve_ports calls docker compose port for each exposed service."""
    manager = DropletManager(dataset_root=Path("."), work_root=Path("."))
    exposed = [
        {"name": "web", "protocol": "http", "service": "web", "container_port": 80, "host_port": 0},
        {"name": "api", "protocol": "tcp", "service": "api", "container_port": 5000, "host_port": 0},
    ]

    def fake_query(project, service, container_port, docker_env):
        return {"web": 11111, "api": 22222}.get(service)

    monkeypatch.setattr(manager, "_query_host_port", fake_query)
    resolved = manager._resolve_ports("proj", exposed, {})

    assert resolved[0]["host_port"] == 11111
    assert resolved[1]["host_port"] == 22222


def test_wait_for_endpoints_uses_exponential_backoff(monkeypatch) -> None:
    """_wait_for_endpoints should back off exponentially, not poll every 1s."""
    manager = DropletManager(dataset_root=Path("."), work_root=Path("."))
    manager.ready_timeout_seconds = 5
    sleeps = []
    monkeypatch.setattr(manager_module.time, "sleep", sleeps.append)

    call_count = [0]

    def flaky_ready(endpoint):
        call_count[0] += 1
        if call_count[0] < 3:
            return False, "not yet"
        return True, ""

    monkeypatch.setattr(manager_module, "_endpoint_ready", flaky_ready)

    manager._wait_for_endpoints(
        [{"type": "tcp", "host": "127.0.0.1", "port": 12345}]
    )

    # First delay = 0.25s, second delay = 0.5s (exponential)
    assert sleeps == [0.25, 0.5]


def test_watchdog_sets_error_when_endpoint_unreachable(monkeypatch) -> None:
    """Watchdog should mark challenge as error if endpoint is down but container is running."""
    manager = DropletManager(dataset_root=Path("."), work_root=Path("."))
    challenge = Challenge(
        id="demo",
        title="Demo",
        description="Demo",
        category="web",
        task_type="web_ctf_online",
        difficulty="easy",
        root=str(Path(".")),
        compose_path=str(Path(".")),
        expose=[{"name": "web", "protocol": "http", "service": "web", "container_port": 80, "host_port": 12345}],
        status="running",
        target_url="http://127.0.0.1:12345",
        ports=[12345],
        compose_project="proj_demo",
    )
    manager.challenges = {"demo": challenge}

    monkeypatch.setattr(manager, "_is_compose_running", lambda c: True)
    monkeypatch.setattr(manager_module, "_endpoint_ready", lambda e: (False, "connection refused"))
    monkeypatch.setattr(manager, "_stop_compose", lambda c: None)

    manager._check_container_health()

    assert challenge.status.value == "error"
    assert "connection refused" in challenge.error_message


def test_compose_ps_json_parser_accepts_multi_container_json_lines() -> None:
    raw = '\n'.join(
        [
            '{"Name":"app","State":"running"}',
            '{"Name":"db","State":"running"}',
        ]
    )

    containers = manager_module._parse_compose_ps_json(raw)

    assert [item["Name"] for item in containers] == ["app", "db"]
