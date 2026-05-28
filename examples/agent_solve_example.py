"""Complete agent workflow: discover challenges, start one, attack, record a submission.

Usage:
    PYTHONPATH=backend:sdk python examples/agent_solve_example.py
"""

from __future__ import annotations

from droplet_sdk import DropletClient


def main() -> None:
    with DropletClient() as client:
        # 1. List all challenges
        challenges = client.list_challenges()
        print(f"[+] {len(challenges)} challenges available")
        for c in challenges:
            print(f"    - {c['id']}: {c['title']} ({c['difficulty']}) [{c['status']}]")

        # 2. Pick the first challenge and start it
        challenge = challenges[0]
        challenge_id = challenge["id"]
        print(f"\n[+] Starting challenge: {challenge_id}")
        challenge = client.start_challenge(challenge_id)
        target_url = challenge["target_url"]
        print(f"[+] Challenge running at: {target_url}")

        # 3. Agent attacks the target with its own tools
        print(f"[!] Agent attacking {target_url} ...")
        # import httpx
        # r = httpx.get(f"{target_url}/api/users")
        # ... fuzz ID, find flag ...

        # 4. Record the flag found by the agent. Do not read challenge source or .env.
        flag = "FLAG{replace_with_agent_found_flag}"
        print("[+] Submitting agent-discovered flag...")
        result = client.submit_answer(challenge_id, flag)
        print(f"[+] Result: accepted={result['accepted']}, judged={result['judged']}")
        if not result["judged"]:
            print("[+] This dataset has no platform-side judge; the submission was recorded only.")

        # 5. Show stats
        stats = client.stats()
        print(f"\n[+] Stats: {stats['solved']}/{stats['total_challenges']} solved")


if __name__ == "__main__":
    main()
