import pytest

from droplet.database import reset_engine, reset_session_cache


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Give every test its own SQLite database file to avoid cross-test pollution."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DROPLET_DATABASE_PATH", str(db_path))
    reset_engine()
    reset_session_cache()
    yield
    reset_engine()
    reset_session_cache()
