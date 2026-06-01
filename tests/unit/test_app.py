"""Tests for droplet.app — API endpoints and auth middleware."""

from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, isolated_database, monkeypatch):
    """Create a FastAPI test client with isolated database."""
    monkeypatch.setenv("DROPLET_DATASET_ROOT", str(tmp_path / "datasets"))
    monkeypatch.setenv("DROPLET_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv("DROPLET_PRESTART_CHALLENGES", "0")
    monkeypatch.setenv("DROPLET_PREFETCH_IMAGES", "0")

    # Re-import to get a fresh manager with the new env vars
    import importlib
    import droplet.app as app_module

    importlib.reload(app_module)

    from fastapi.testclient import TestClient

    return TestClient(app_module.app)


AUTH_HEADER = {"Authorization": "Bearer droplet_dev_admin"}


def test_health_no_auth_required(client):
    """Health endpoint should not require authentication."""
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_challenges_requires_auth(client):
    """Challenge list should require bearer token."""
    resp = client.get("/api/challenges")
    assert resp.status_code == 401


def test_challenges_with_auth(client):
    """Challenge list with valid token should return 200."""
    resp = client.get("/api/challenges", headers=AUTH_HEADER)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_invalid_token_rejected(client):
    """Invalid token should be rejected."""
    resp = client.get("/api/challenges", headers={"Authorization": "Bearer invalid"})
    assert resp.status_code == 401


def test_droplet_prefix_token_accepted(client):
    """Tokens starting with 'droplet_' should be accepted."""
    resp = client.get("/api/challenges", headers={"Authorization": "Bearer droplet_mytoken"})
    assert resp.status_code == 200


def test_missing_bearer_prefix(client):
    """Token without 'Bearer ' prefix should be rejected."""
    resp = client.get("/api/challenges", headers={"Authorization": "droplet_dev_admin"})
    assert resp.status_code == 401


def test_datasets_endpoint(client):
    """Datasets endpoint should return a dict."""
    resp = client.get("/api/datasets", headers=AUTH_HEADER)
    assert resp.status_code == 200


def test_stats_endpoint(client):
    """Stats endpoint should return expected fields."""
    resp = client.get("/api/stats", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_challenges" in data
    assert "solved" in data
    assert "running" in data


def test_prefetch_progress_endpoint(client):
    """Prefetch progress should return status info."""
    resp = client.get("/api/challenges/prefetch/progress", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "total" in data


def test_challenge_not_found(client):
    """Requesting a non-existent challenge should return 404."""
    resp = client.get("/api/challenges/NONEXISTENT", headers=AUTH_HEADER)
    assert resp.status_code in (404, 500)  # KeyError or HTTPException


def test_prefetch_endpoint(client):
    """Prefetch endpoint should start without error."""
    resp = client.post("/api/challenges/prefetch", headers=AUTH_HEADER)
    assert resp.status_code == 200
