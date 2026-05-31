from pathlib import Path

from droplet.manager import DropletManager


def test_demo_xbow_challenges_are_discovered() -> None:
    # Uses root droplet.yaml (schema_version: 2) which discovers all datasets
    manager = DropletManager(dataset_root=Path("datasets"))
    manager.load_tasks()

    # xbow is a superset of demo-xbow (shared IDs: xben-001~005)
    # After loading both datasets, xbow overwrites demo-xbow for overlapping IDs
    assert len(manager.challenges) >= 5
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
