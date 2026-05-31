from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class DropletClient:
    base_url: str = "http://127.0.0.1:1349"
    api_token: str = "droplet_dev_admin"
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
        """List all challenges with their current status and target URLs."""
        return self._request("GET", "/api/challenges")

    def get_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Get one challenge with current runtime state."""
        return self._request("GET", f"/api/challenges/{challenge_id}")

    def list_events(
        self, challenge_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """List platform-visible audit events."""
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
        """Report an external agent-visible event without exposing hidden reasoning."""
        return self._request(
            "POST",
            f"/api/challenges/{challenge_id}/events",
            json={"event_type": event_type, "message": message, "level": level, "data": data or {}},
        )

    def start_all_challenges(self, challenge_ids: list[str] | None = None) -> dict[str, Any]:
        """Start all selected challenge environments."""
        payload = {"challenge_ids": challenge_ids} if challenge_ids else None
        return self._request("POST", "/api/challenges/start-all", json=payload)

    def stop_all_challenges(self) -> dict[str, Any]:
        """Stop all running challenge environments."""
        return self._request("POST", "/api/challenges/stop-all")

    def start_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Start a challenge environment. Returns updated challenge with target_url."""
        return self._request("POST", f"/api/challenges/{challenge_id}/start")

    def stop_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Stop a challenge environment."""
        return self._request("POST", f"/api/challenges/{challenge_id}/stop")

    def reset_challenge(self, challenge_id: str) -> dict[str, Any]:
        """Reset a challenge environment (stop + restart)."""
        return self._request("POST", f"/api/challenges/{challenge_id}/reset")

    def submit_answer(self, challenge_id: str, answer: str) -> dict[str, Any]:
        """Record a submitted flag or answer. It is judged only if the challenge config provides a judge."""
        return self._request(
            "POST", f"/api/challenges/{challenge_id}/submit", json={"answer": answer}
        )

    def view_hint(self, challenge_id: str) -> dict[str, Any]:
        """Request a hint for a challenge. First use reduces score by 10%."""
        return self._request("POST", f"/api/challenges/{challenge_id}/hint")

    def stats(self) -> dict[str, Any]:
        """Get overall statistics."""
        return self._request("GET", "/api/stats")

    # ------------------------------------------------------------------
    # Compatibility (Tencent-style API)
    # ------------------------------------------------------------------

    def compat_challenges(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/challenges")

    def compat_hint(self, challenge_code: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/hint/{challenge_code}")

    def compat_submit_answer(self, challenge_code: str, answer: str) -> dict[str, Any]:
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
