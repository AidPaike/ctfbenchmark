from __future__ import annotations

from droplet_sdk.client import DropletClient


def test_client_defaults_to_environment_base_url_and_token(monkeypatch) -> None:
    monkeypatch.setenv("DROPLET_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("DROPLET_API_TOKEN", "configured-secret")

    client = DropletClient()
    try:
        assert client.base_url == "http://127.0.0.1:9999"
        assert client.api_token == "configured-secret"
        assert client._client.headers["authorization"] == "Bearer configured-secret"
    finally:
        client.close()
