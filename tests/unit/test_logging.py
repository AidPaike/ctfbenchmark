from __future__ import annotations

import logging

import pytest
from sqlmodel import Session, select

from droplet.database import SystemLog, get_engine, init_db, reset_engine
from droplet.logging_config import ColorFormatter, SQLiteLogHandler, setup_logging


@pytest.fixture(autouse=True)
def isolated_logging_db(tmp_path):
    """Provide a fresh SQLite DB for each logging test."""
    reset_engine()
    db_path = tmp_path / "test_logs.db"
    import os

    os.environ["DROPLET_DATABASE_PATH"] = str(db_path)
    init_db()
    yield
    reset_engine()
    os.environ.pop("DROPLET_DATABASE_PATH", None)


class TestColorFormatter:
    def test_format_includes_timestamp_level_name_message(self):
        formatter = ColorFormatter()
        record = logging.makeLogRecord(
            {
                "name": "test.logger",
                "level": logging.INFO,
                "levelname": "INFO",
                "msg": "hello world",
                "args": (),
                "pathname": "/tmp/test.py",
                "lineno": 42,
            }
        )
        result = formatter.format(record)
        assert "INFO" in result
        assert "test.logger:42" in result
        assert "hello world" in result

    def test_format_exception_includes_traceback(self):
        formatter = ColorFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.makeLogRecord(
                {
                    "name": "test.logger",
                    "level": logging.ERROR,
                    "levelname": "ERROR",
                    "msg": "failed",
                    "args": (),
                    "exc_info": logging.sys.exc_info(),
                    "pathname": "/tmp/test.py",
                    "lineno": 1,
                }
            )
        exc_text = formatter.formatException(record.exc_info)
        assert "boom" in exc_text
        assert "ValueError" in exc_text


class TestSQLiteLogHandler:
    def test_emit_persists_log_to_database(self):
        handler = SQLiteLogHandler()
        logger = logging.getLogger("test_emit")
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        logger.info("test message", extra={"challenge_id": "demo-001"})

        engine = get_engine()
        with Session(engine) as session:
            results = session.exec(select(SystemLog)).all()
            assert len(results) == 1
            log = results[0]
            assert log.level == "INFO"
            assert log.logger == "test_emit"
            assert "test message" in log.message
            assert log.source_file is not None
            assert log.source_line is not None
            assert '"challenge_id": "demo-001"' in log.data

    def test_emit_stores_exception_text(self):
        handler = SQLiteLogHandler()
        logger = logging.getLogger("test_exc")
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        try:
            raise RuntimeError("something broke")
        except RuntimeError:
            logger.exception("handled error")

        engine = get_engine()
        with Session(engine) as session:
            results = session.exec(select(SystemLog)).all()
            assert len(results) == 1
            log = results[0]
            assert log.level == "ERROR"
            assert log.exception is not None
            assert "something broke" in log.exception
            assert "RuntimeError" in log.exception

    def test_emit_respects_level(self):
        handler = SQLiteLogHandler(level=logging.WARNING)
        logger = logging.getLogger("test_level")
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warn msg")

        engine = get_engine()
        with Session(engine) as session:
            results = session.exec(select(SystemLog)).all()
            assert len(results) == 1
            assert results[0].level == "WARNING"


class TestSetupLogging:
    def test_creates_stream_and_db_handlers(self):
        setup_logging()
        root = logging.getLogger()
        assert any(isinstance(h, SQLiteLogHandler) for h in root.handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)

    def test_can_be_called_multiple_times_without_duplicate_handlers(self):
        setup_logging()
        setup_logging()
        root = logging.getLogger()
        db_handlers = [h for h in root.handlers if isinstance(h, SQLiteLogHandler)]
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
        assert len(db_handlers) == 1
        assert len(stream_handlers) == 1

    def test_log_records_to_database(self):
        setup_logging()
        logger = logging.getLogger("integration_test")
        logger.info("integration message")

        engine = get_engine()
        with Session(engine) as session:
            results = session.exec(select(SystemLog)).all()
            assert len(results) >= 1
            messages = [r.message for r in results]
            assert any("integration message" in m for m in messages)


class TestSystemLogTable:
    def test_table_exists_after_init_db(self):
        engine = get_engine()
        with Session(engine) as session:
            # If the table doesn't exist, this would raise an OperationalError
            results = session.exec(select(SystemLog)).all()
            assert isinstance(results, list)


class TestEarlyLogLoss:
    def test_setup_logging_creates_tables_before_handler(self, tmp_path, monkeypatch):
        """setup_logging must call init_db() internally so the first log is not lost.

        Regression test for issue #5: when setup_logging() runs before init_db(),
        the SQLiteLogHandler tries to write to a table that doesn't exist yet.
        """
        reset_engine()
        db_path = tmp_path / "fresh.db"
        monkeypatch.setenv("DROPLET_DATABASE_PATH", str(db_path))
        reset_engine()

        # Do NOT call init_db() — simulate first-ever startup
        setup_logging()
        logger = logging.getLogger("first_startup")
        logger.info("early log during first startup")

        engine = get_engine()
        with Session(engine) as session:
            results = session.exec(select(SystemLog)).all()
            assert len(results) >= 1
            assert any("early log during first startup" in r.message for r in results)

        reset_engine()
        monkeypatch.delenv("DROPLET_DATABASE_PATH", raising=False)
