from pathlib import Path

from droplet.manager import DropletManager


def test_demo_xbow_challenges_are_discovered() -> None:
    manager = DropletManager(dataset_root=Path("datasets/demo-xbow"))
    manager.load_tasks()

    assert set(manager.challenges) == {
        "xben-001-24",
        "xben-002-24",
        "xben-003-24",
        "xben-004-24",
        "xben-005-24",
    }
    for challenge in manager.challenges.values():
        assert challenge.task_type == "web_ctf_online"
        assert challenge.root.endswith(challenge.id.upper())
        assert challenge.expose
        assert challenge.judge_mode == "record_only"


def test_demo_xbow_templates_do_not_contain_machine_specific_proxy() -> None:
    root = Path("datasets/demo-xbow/challenges")
    forbidden = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "192.168.3.67")
    for path in list(root.rglob("Dockerfile")) + list(root.rglob("docker-compose.yml")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} contains machine-specific proxy token {token}"
