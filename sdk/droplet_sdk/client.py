from __future__ import annotations

import time
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class DropletClient:
    base_url: str = field(
        default_factory=lambda: os.getenv("DROPLET_BASE_URL", "http://127.0.0.1:1349")
    )
    api_token: str = field(
        default_factory=lambda: os.getenv("DROPLET_API_TOKEN", "droplet_dev_admin")
    )
    timeout: float = 60.0
    retries: int = 2

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.api_token}"},
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def list_challenges(self) -> list[dict[str, Any]]:
        """List all challenges with their current status and target URLs.

        Returns a list of challenge dicts. Key fields:
          - id: challenge identifier (e.g. "xben-001-24")
          - status: "not_started" | "starting" | "running" | "error" | "solved"
          - target_url: access URL (only set when status == "running")
          - ports: list of exposed ports
          - solved: whether the challenge has been solved
          - score: current score (0.0 ~ 1.0)
        """
        return self._request("GET", "/api/challenges")

    def get_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Get one challenge with current runtime state.

        Args:
            challenge_id: The challenge identifier (e.g. "xben-001-24").

        Returns:
            Same fields as list_challenges(), but for a single challenge.
        """
        return self._request("GET", f"/api/challenges/{challenge_id}")

    def list_events(
        self, challenge_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """List platform-visible audit events.

        Args:
            challenge_id: Filter by challenge. None returns all events.
            limit: Max number of events to return (1-1000, default 200).
        """
        params = {"limit": limit}
        if challenge_id:
            params["challenge_id"] = challenge_id
        return self._request("GET", "/api/events", params=params)

    def report_event(
        self,
        challenge_id: str,
        event_type: str,
        message: str,
        *,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Report an agent event for audit trail. Does not affect scoring.

        Args:
            challenge_id: The challenge this event relates to.
            event_type: Event type identifier (e.g. "vulnerability_found").
            message: Human-readable description.
            level: "info" | "warning" | "error".
            data: Optional structured data dict.
        """
        return self._request(
            "POST",
            f"/api/challenges/{challenge_id}/events",
            json={"event_type": event_type, "message": message, "level": level, "data": data or {}},
        )

    def start_all_challenges(self, challenge_ids: list[str] | None = None) -> dict[str, Any]:
        """Start all or selected challenge environments.

        Args:
            challenge_ids: List of challenge IDs to start. None starts all.

        Returns:
            Dict with "started", "already_running", "errors" keys.
        """
        payload = {"challenge_ids": challenge_ids} if challenge_ids else None
        return self._request("POST", "/api/challenges/start-all", json=payload)

    def stop_all_challenges(self) -> dict[str, Any]:
        """Stop all running challenge environments."""
        return self._request("POST", "/api/challenges/stop-all")

    def prefetch_images(self, challenge_ids: list[str] | None = None) -> dict[str, Any]:
        """Pre-pull Docker images to speed up subsequent starts.

        Args:
            challenge_ids: List of challenge IDs. None prefetches all.
        """
        payload = {"challenge_ids": challenge_ids} if challenge_ids else None
        return self._request("POST", "/api/challenges/prefetch", json=payload)

    def start_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Start a challenge environment.

        The start is asynchronous — poll get_challenge() until status == "running"
        and target_url is set before attempting to access the challenge.

        Args:
            challenge_id: The challenge to start (e.g. "xben-001-24").

        Returns:
            Challenge dict with updated status (likely "starting").
        """
        return self._request("POST", f"/api/challenges/{challenge_id}/start")

    def stop_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Stop a challenge environment and release its resources.

        Args:
            challenge_id: The challenge to stop.

        Returns:
            Challenge dict with updated status.
        """
        return self._request("POST", f"/api/challenges/{challenge_id}/stop")

    def reset_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Reset a challenge (stop + restart). Clears runtime state.

        Args:
            challenge_id: The challenge to reset.

        Returns:
            Challenge dict with updated status (likely "starting").
        """
        return self._request("POST", f"/api/challenges/{challenge_id}/reset")

    def submit_answer(self, challenge_id: str, answer: str) -> dict[str, Any]:
        """Submit a flag or answer for a challenge.

        Args:
            challenge_id: The challenge to submit to.
            answer: The flag or answer string.

        Returns:
            Dict with keys:
              - accepted (bool): whether the submission was recorded
              - judged (bool): whether automatic judging was performed
              - correct (bool|None): result (only when judged=true)
              - is_solved (bool): whether the challenge is now solved
              - submission_count (int): total submissions for this challenge
              - message (str): human-readable result
        """
        return self._request(
            "POST", f"/api/challenges/{challenge_id}/submit", json={"answer": answer}
        )

    def view_hint(self, challenge_id: str) -> dict[str, Any]:
        """View a hint for a challenge. First use incurs a 10% score penalty.

        Args:
            challenge_id: The challenge to get a hint for.

        Returns:
            Dict with keys:
              - content (str): hint text
              - penalty (float): score deduction from this request
              - first_use (bool): whether this was the first hint viewed
              - hint_penalty (float): cumulative penalty (0.0 ~ 1.0)
        """
        return self._request("POST", f"/api/challenges/{challenge_id}/hint")

    def stats(self) -> dict[str, Any]:
        """Get overall benchmark statistics (total, running, solved counts, etc.)."""
        return self._request("GET", "/api/stats")

    # ------------------------------------------------------------------
    # Compatibility (Tencent-style API)
    # These map to the same backend logic but use Tencent's field names.
    # Prefer the native methods above unless your agent is built for
    # the Tencent API format.
    # ------------------------------------------------------------------

    def compat_challenges(self) -> dict[str, Any]:
        """List challenges in Tencent-compatible format.

        Returns:
            Dict with "current_stage" and "challenges" list. Each challenge has
            "challenge_code", "points", "target_info" (ip + port) instead of
            the native "id", "target_url", "ports".
        """
        return self._request("GET", "/api/v1/challenges")

    def compat_hint(self, challenge_code: str) -> dict[str, Any]:
        """Get a hint in Tencent-compatible format.

        Args:
            challenge_code: The challenge code (e.g. "xben-001-24").

        Returns:
            Dict with "hint_content", "penalty_points", "first_use".
        """
        return self._request("GET", f"/api/v1/hint/{challenge_code}")

    def compat_submit_answer(self, challenge_code: str, answer: str) -> dict[str, Any]:
        """Submit an answer in Tencent-compatible format.

        Args:
            challenge_code: The challenge code.
            answer: The flag or answer string.

        Returns:
            Dict with "correct", "judged", "accepted", "earned_points", "is_solved", "message".
        """
        return self._request(
            "POST", "/api/v1/answer", json={"challenge_code": challenge_code, "answer": answer}
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for retry_index in range(self.retries + 1):
            try:
                response = self._client.request(method, path, **kwargs)
                if response.status_code in {429, 500, 502, 503, 504} and retry_index < self.retries:
                    time.sleep(min(2**retry_index, 5))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if retry_index >= self.retries:
                    raise
                time.sleep(min(2**retry_index, 5))
        if last_error:
            raise last_error
        raise RuntimeError("request failed without response")

    def __enter__(self) -> DropletClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
