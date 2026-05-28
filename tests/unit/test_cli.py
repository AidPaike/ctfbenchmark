from __future__ import annotations

import json

from droplet_sdk import cli


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def list_challenges(self):
        return [
            {
                "id": "xben-001-24",
                "status": "running",
                "target_url": "http://127.0.0.1:30001",
                "ports": [30001],
                "error_message": None,
            }
        ]

    def list_events(self, challenge_id=None, limit=200):
        return [{"event_type": "challenge_started", "challenge_id": challenge_id, "limit": limit}]

    def report_event(self, challenge_id, event_type, message, level="info", data=None):
        return {"challenge_id": challenge_id, "event_type": event_type, "message": message, "level": level}

    def start_all_challenges(self, challenge_ids=None):
        return {"started": challenge_ids or ["xben-001-24"], "errors": {}}

    def stop_all_challenges(self):
        return {"stopped": ["xben-001-24"], "errors": {}}

    def start_challenge(self, challenge_id):
        return {"id": challenge_id, "status": "running"}

    def stop_challenge(self, challenge_id):
        return {"id": challenge_id, "status": "not_started"}

    def reset_challenge(self, challenge_id):
        return {"id": challenge_id, "status": "running"}

    def submit_answer(self, challenge_id, answer):
        return {"challenge_id": challenge_id, "accepted": True, "judged": False, "correct": None}

    def view_hint(self, challenge_id):
        return {"challenge_id": challenge_id, "content": "hint"}

    def stats(self):
        return {"total_challenges": 1, "solved": 0}

    def compat_challenges(self):
        return {"current_stage": "competition", "challenges": []}

    def compat_hint(self, challenge_code):
        return {"challenge_code": challenge_code, "hint_content": "hint"}

    def compat_submit_answer(self, challenge_code, answer):
        return {"challenge_code": challenge_code, "accepted": True, "judged": False, "correct": False}


def test_cli_challenges_start_all_and_submit_print_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "DropletClient", FakeClient)

    assert cli.main(["challenges"]) == 0
    challenges = json.loads(capsys.readouterr().out)
    assert challenges[0]["id"] == "xben-001-24"

    assert cli.main(["start-all", "--challenge-id", "xben-001-24"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["started"] == ["xben-001-24"]

    assert cli.main(["submit", "xben-001-24", "flag{ok}"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["accepted"] is True
    assert result["judged"] is False


def test_cli_preflight_returns_success_when_all_selected_challenges_are_ready(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "DropletClient", FakeClient)

    assert cli.main(["preflight", "--challenge-id", "xben-001-24"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["ready_count"] == 1
    assert result["failed"] == []


def test_cli_preflight_returns_failure_when_a_challenge_is_not_ready(monkeypatch, capsys) -> None:
    class FailingClient(FakeClient):
        def list_challenges(self):
            return [
                {
                    "id": "xben-004-24",
                    "status": "error",
                    "target_url": None,
                    "ports": [],
                    "error_message": "compose timed out",
                }
            ]

        def start_challenge(self, challenge_id):
            raise RuntimeError("compose timed out")

    monkeypatch.setattr(cli, "DropletClient", FailingClient)

    assert cli.main(["preflight"]) == 1

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["failed"][0]["id"] == "xben-004-24"


def test_cli_events_and_report_event_print_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "DropletClient", FakeClient)

    assert cli.main(["events", "--challenge-id", "xben-001-24", "--limit", "10"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert events[0]["challenge_id"] == "xben-001-24"
    assert events[0]["limit"] == 10

    assert cli.main(["report-event", "xben-001-24", "agent_event", "curl target"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["event_type"] == "agent_event"
    assert result["message"] == "curl target"
