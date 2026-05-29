from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any

from sqlmodel import Session

from droplet.database import SystemLog, get_engine, init_db


# ANSI color codes for terminal output
# 终端输出的 ANSI 颜色代码
_COLORS = {
    "DEBUG": "\x1b[38;5;245m",      # gray
    "INFO": "\x1b[38;5;82m",        # green
    "WARNING": "\x1b[38;5;220m",    # yellow
    "ERROR": "\x1b[38;5;196m",      # red
    "CRITICAL": "\x1b[1;38;5;196m", # bold red
    "RESET": "\x1b[0m",
    "DIM": "\x1b[38;5;240m",
    "BOLD": "\x1b[1m",
}


class SQLiteLogHandler(logging.Handler):
    """A logging.Handler that persists records to SQLite via SQLModel."""

    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self._engine = get_engine()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc_text = None
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info))

            data = {}
            for key in ("challenge_id", "docker_command", "duration_ms", "status_code", "method", "path"):
                if hasattr(record, key):
                    data[key] = getattr(record, key)

            log_entry = SystemLog(
                level=record.levelname,
                logger=record.name,
                message=self.format(record),
                source_file=record.pathname,
                source_line=record.lineno,
                exception=exc_text,
                data=json.dumps(data, ensure_ascii=False, default=str) if data else "{}",
            )
            with Session(self._engine) as session:
                session.add(log_entry)
                session.commit()
        except Exception:
            self.handleError(record)


class ColorFormatter(logging.Formatter):
    """Terminal formatter with timestamps, level colors, and clean layout."""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None) -> None:
        super().__init__(fmt, datefmt)
        self._use_color = sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        level = record.levelname
        name = record.name
        msg = record.getMessage()

        if self._use_color:
            color = _COLORS.get(level, _COLORS["RESET"])
            reset = _COLORS["RESET"]
            dim = _COLORS["DIM"]
            return f"{dim}{ts}{reset} {color}[{level:8}]{reset} {dim}{name}:{record.lineno}{reset} {msg}"
        return f"{ts} [{level:8}] {name}:{record.lineno} {msg}"

    def formatException(self, ei: Any) -> str:
        text = super().formatException(ei)
        if self._use_color:
            return f"{_COLORS['ERROR']}{text}{_COLORS['RESET']}"
        return text


def setup_logging(
    level: int = logging.INFO,
    database_level: int = logging.INFO,
    terminal_level: int = logging.DEBUG,
) -> None:
    """Configure root logger with SQLite + terminal handlers.

    Args:
        level: Minimum global log level.
        database_level: Minimum level for SQLite persistence.
        terminal_level: Minimum level for terminal output.
    """
    # Ensure DB tables exist before creating SQLiteLogHandler.
    # Fixes issue #5: first startup loses early logs because the table
    # doesn't exist yet when setup_logging() runs before init_db().
    init_db()

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates on re-init
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Terminal handler — beautiful colored output
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(terminal_level)
    stream_formatter = ColorFormatter()
    stream_handler.setFormatter(stream_formatter)
    root.addHandler(stream_handler)

    # SQLite handler — structured persistence
    db_handler = SQLiteLogHandler(level=database_level)
    db_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    db_handler.setFormatter(db_formatter)
    root.addHandler(db_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
