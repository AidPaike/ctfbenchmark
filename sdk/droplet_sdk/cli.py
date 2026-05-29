from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from typing import Any

import httpx

from droplet_sdk.client import DropletClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Droplet benchmark platform CLI")
    parser.add_argument("--base-url", default="http://127.0.0.1:1349")
    parser.add_argument("--api-token", default="droplet_dev_admin")
    parser.add_argument("--timeout", type=float, default=600.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check local client and backend readiness")

    serve = subparsers.add_parser("serve", help="Run the Droplet backend")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=1349)
    serve.add_argument("--reload", action="store_true")

    subparsers.add_parser("challenges", help="List all challenges")

    events = subparsers.add_parser("events", help="List audit events")
    events.add_argument("--challenge-id")
    events.add_argument("--limit", type=int, default=200)

    report_event = subparsers.add_parser("report-event", help="Append an external agent event")
    report_event.add_argument("challenge_id")
    report_event.add_argument("event_type")
    report_event.add_argument("message")
    report_event.add_argument("--level", default="info")

    preflight = subparsers.add_parser("preflight", help="Start challenges and fail if any challenge is not ready")
    preflight.add_argument("--challenge-id", action="append", dest="challenge_ids")
    preflight.add_argument("--no-start", action="store_true", help="Only check current status; do not call start-all")

    start_all = subparsers.add_parser("start-all", help="Start all or selected challenge environments")
    start_all.add_argument("--challenge-id", action="append", dest="challenge_ids")

    subparsers.add_parser("stop-all", help="Stop all running challenge environments")

    start = subparsers.add_parser("start", help="Start a challenge environment")
    start.add_argument("challenge_id")

    stop = subparsers.add_parser("stop", help="Stop a challenge environment")
    stop.add_argument("challenge_id")

    reset = subparsers.add_parser("reset", help="Reset a challenge environment")
    reset.add_argument("challenge_id")

    submit = subparsers.add_parser("submit", help="Record a submitted flag or answer")
    submit.add_argument("challenge_id")
    submit.add_argument("answer")

    hint = subparsers.add_parser("hint", help="Get a challenge hint")
    hint.add_argument("challenge_id")

    subparsers.add_parser("stats", help="Get overall statistics")

    subparsers.add_parser("compat-challenges", help="List Tencent-compatible challenges")
    compat_hint = subparsers.add_parser("compat-hint", help="Get a Tencent-compatible hint")
    compat_hint.add_argument("challenge_code")
    compat_submit = subparsers.add_parser("compat-submit", help="Submit a Tencent-compatible answer")
    compat_submit.add_argument("challenge_code")
    compat_submit.add_argument("answer")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "doctor":
        return _doctor(args)

    with DropletClient(base_url=args.base_url, api_token=args.api_token, timeout=args.timeout) as client:
        if args.command == "challenges":
            return _print(client.list_challenges())
        if args.command == "events":
            return _print(client.list_events(args.challenge_id, args.limit))
        if args.command == "report-event":
            return _print(client.report_event(args.challenge_id, args.event_type, args.message, level=args.level))
        if args.command == "preflight":
            return _preflight(client, args.challenge_ids, args.no_start)
        if args.command == "start-all":
            return _print(client.start_all_challenges(args.challenge_ids))
        if args.command == "stop-all":
            return _print(client.stop_all_challenges())
        if args.command == "start":
            return _print(client.start_challenge(args.challenge_id))
        if args.command == "stop":
            return _print(client.stop_challenge(args.challenge_id))
        if args.command == "reset":
            return _print(client.reset_challenge(args.challenge_id))
        if args.command == "submit":
            return _print(client.submit_answer(args.challenge_id, args.answer))
        if args.command == "hint":
            return _print(client.view_hint(args.challenge_id))
        if args.command == "stats":
            return _print(client.stats())
        if args.command == "compat-challenges":
            return _print(client.compat_challenges())
        if args.command == "compat-hint":
            return _print(client.compat_hint(args.challenge_code))
        if args.command == "compat-submit":
            return _print(client.compat_submit_answer(args.challenge_code, args.answer))

    parser.error(f"Unknown command: {args.command}")
    return 2


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("droplet.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _doctor(args: argparse.Namespace) -> int:
    checks: dict[str, Any] = {
        "docker": bool(shutil.which("docker")),
        "base_url": args.base_url,
        "backend": False,
    }
    try:
        response = httpx.get(f"{args.base_url.rstrip('/')}/api/health", timeout=3.0, trust_env=False)
        checks["backend"] = response.status_code == 200
        checks["health"] = response.json() if response.status_code == 200 else response.text
    except Exception as exc:
        checks["backend_error"] = str(exc)
    return _print(checks)


def _preflight(client: DropletClient, challenge_ids: list[str] | None, no_start: bool) -> int:
    initial = client.list_challenges()
    selected_ids = challenge_ids or [str(challenge["id"]) for challenge in initial]
    start_result: dict[str, Any] | None = None

    if not no_start:
        start_result = {"started": [], "already_running": [], "errors": {}}
        initial_by_id = {str(challenge["id"]): challenge for challenge in initial}
        total = len(selected_ids)
        for index, challenge_id in enumerate(selected_ids, start=1):
            current = initial_by_id.get(challenge_id, {})
            if current.get("status") == "running" and current.get("ports"):
                start_result["already_running"].append(challenge_id)
                print(
                    f"[{index}/{total}] {challenge_id} 已在运行: {current.get('target_url')}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            print(f"[{index}/{total}] 正在启动 {challenge_id} ...", file=sys.stderr, flush=True)
            try:
                updated = client.start_challenge(challenge_id)
                start_result["started"].append(challenge_id)
                print(
                    f"[{index}/{total}] {challenge_id} 启动请求已发送: {updated.get('status')}",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:
                start_result["errors"][challenge_id] = str(exc)
                print(f"[{index}/{total}] {challenge_id} 启动失败: {exc}", file=sys.stderr, flush=True)

    challenges = _wait_for_preflight_ready(
        client,
        selected_ids,
        timeout=getattr(client, "timeout", 600.0) if not no_start else 0,
    )
    selected = set(selected_ids)
    challenges = [challenge for challenge in challenges if challenge["id"] in selected]

    ready = [
        challenge
        for challenge in challenges
        if challenge.get("status") == "running" and challenge.get("ports")
    ]
    failed = [
        {
            "id": challenge.get("id"),
            "status": challenge.get("status"),
            "target_url": challenge.get("target_url"),
            "ports": challenge.get("ports", []),
            "error_message": challenge.get("error_message"),
        }
        for challenge in challenges
        if challenge.get("status") != "running" or not challenge.get("ports")
    ]
    payload = {
        "ok": not failed,
        "ready_count": len(ready),
        "failed_count": len(failed),
        "start_result": start_result,
        "ready": [
            {
                "id": challenge["id"],
                "target_url": challenge.get("target_url"),
                "ports": challenge.get("ports", []),
            }
            for challenge in ready
        ],
        "failed": failed,
    }
    _print(payload)
    return 0 if payload["ok"] else 1


def _wait_for_preflight_ready(
    client: DropletClient,
    selected_ids: list[str],
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    selected = set(selected_ids)
    deadline = time.monotonic() + max(timeout, 0)
    challenges = client.list_challenges()
    while timeout > 0 and time.monotonic() < deadline:
        selected_challenges = [challenge for challenge in challenges if challenge.get("id") in selected]
        pending = [
            challenge
            for challenge in selected_challenges
            if challenge.get("status") in {"starting", "stopping"}
        ]
        if not pending:
            return challenges
        pending_ids = ", ".join(str(challenge.get("id")) for challenge in pending)
        print(f"等待题目就绪: {pending_ids}", file=sys.stderr, flush=True)
        time.sleep(2)
        challenges = client.list_challenges()
    return challenges


def _print(payload: Any) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
