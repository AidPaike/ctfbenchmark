import os

from droplet_sdk.client import DropletClient

try:
    from fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install MCP support with: pip install -e '.[mcp]'") from exc


mcp = FastMCP("Droplet")


def _client() -> DropletClient:
    return DropletClient(
        base_url=os.getenv("DROPLET_BASE_URL", "http://127.0.0.1:1349"),
        api_token=os.getenv("DROPLET_API_TOKEN", "droplet_dev_admin"),
    )


@mcp.tool()
def list_challenges() -> dict:
    """List all challenges with their current status and target URLs."""
    with _client() as api:
        return {"challenges": api.list_challenges()}


@mcp.tool()
def start_all_challenges(challenge_ids: list[str] | None = None) -> dict:
    """Start all or selected challenge environments."""
    with _client() as api:
        return api.start_all_challenges(challenge_ids)


@mcp.tool()
def stop_all_challenges() -> dict:
    """Stop all running challenge environments."""
    with _client() as api:
        return api.stop_all_challenges()


@mcp.tool()
def start_challenge(challenge_id: str) -> dict:
    """Start a challenge environment. Returns the challenge with target_url."""
    with _client() as api:
        return api.start_challenge(challenge_id)


@mcp.tool()
def stop_challenge(challenge_id: str) -> dict:
    """Stop a challenge environment."""
    with _client() as api:
        return api.stop_challenge(challenge_id)


@mcp.tool()
def reset_challenge(challenge_id: str) -> dict:
    """Reset a challenge environment (stop and restart)."""
    with _client() as api:
        return api.reset_challenge(challenge_id)


@mcp.tool()
def submit_answer(challenge_id: str, answer: str) -> dict:
    """Record a submitted flag or answer. It is judged only if the challenge config provides a judge."""
    with _client() as api:
        return api.submit_answer(challenge_id, answer)


@mcp.tool()
def view_hint(challenge_id: str) -> dict:
    """Request a hint for a challenge. Each hint reduces score by 10%."""
    with _client() as api:
        return api.view_hint(challenge_id)


@mcp.tool()
def get_stats() -> dict:
    """Get overall statistics."""
    with _client() as api:
        return api.stats()


@mcp.tool()
def list_events(challenge_id: str | None = None, limit: int = 200) -> dict:
    """List platform-visible audit events for all challenges or one challenge."""
    with _client() as api:
        return {"events": api.list_events(challenge_id, limit)}


@mcp.tool()
def report_event(challenge_id: str, event_type: str, message: str, level: str = "info") -> dict:
    """Report an external agent event without exposing hidden chain-of-thought."""
    with _client() as api:
        return api.report_event(challenge_id, event_type, message, level=level)


@mcp.tool()
def get_compat_challenges() -> dict:
    """List Tencent-compatible challenges."""
    with _client() as api:
        return api.compat_challenges()


@mcp.tool()
def get_compat_hint(challenge_code: str) -> dict:
    """Get a Tencent-compatible challenge hint."""
    with _client() as api:
        return api.compat_hint(challenge_code)


@mcp.tool()
def submit_compat_answer(challenge_code: str, answer: str) -> dict:
    """Submit a Tencent-compatible challenge answer."""
    with _client() as api:
        return api.compat_submit_answer(challenge_code, answer)


if __name__ == "__main__":
    mcp.run()
