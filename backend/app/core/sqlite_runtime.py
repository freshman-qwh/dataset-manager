"""SQLite runtime settings shared by the app, tests, and isolated benchmarks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

SQLITE_BUSY_TIMEOUT_MS = 5_000
SQLITE_WAL_AUTOCHECKPOINT_PAGES = 1_000
SQLITE_CHECKPOINT_MODES = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}


def configure_sqlite_engine(engine: Engine) -> Engine:
    """Apply per-connection safeguards when the engine targets SQLite."""
    if engine.dialect.name != "sqlite":
        return engine
    event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


def initialize_sqlite_runtime(engine: Engine) -> str | None:
    """Enable persistent WAL mode once before normal application traffic."""
    if engine.dialect.name != "sqlite":
        return None
    with engine.begin() as connection:
        value = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()
    return str(value).lower()


def checkpoint_sqlite_wal(
    engine: Engine,
    mode: str = "PASSIVE",
) -> dict[str, int | str]:
    """Run an explicit checkpoint and return SQLite's busy/log/checkpoint counts."""
    normalized_mode = mode.upper()
    if normalized_mode not in SQLITE_CHECKPOINT_MODES:
        raise ValueError(f"Unsupported SQLite checkpoint mode: {mode}")
    if engine.dialect.name != "sqlite":
        return {
            "mode": normalized_mode.lower(),
            "busy": 0,
            "log_pages": 0,
            "checkpointed_pages": 0,
        }
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            f"PRAGMA wal_checkpoint({normalized_mode})"
        ).one()
    return {
        "mode": normalized_mode.lower(),
        "busy": int(row[0]),
        "log_pages": int(row[1]),
        "checkpointed_pages": int(row[2]),
    }


def sqlite_runtime_snapshot(
    engine: Engine,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Read effective settings and file sizes without changing database content."""
    if engine.dialect.name != "sqlite":
        return {"dialect": engine.dialect.name}
    with engine.connect() as connection:
        snapshot: dict[str, Any] = {
            "dialect": "sqlite",
            "journal_mode": str(
                connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
            ).lower(),
            "foreign_keys": bool(
                connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            ),
            "busy_timeout_ms": int(
                connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
            ),
            "synchronous": int(
                connection.exec_driver_sql("PRAGMA synchronous").scalar_one()
            ),
            "wal_autocheckpoint_pages": int(
                connection.exec_driver_sql(
                    "PRAGMA wal_autocheckpoint"
                ).scalar_one()
            ),
        }
    if database_path is not None:
        wal_path = Path(f"{database_path}-wal")
        snapshot["database_bytes"] = (
            database_path.stat().st_size if database_path.exists() else 0
        )
        snapshot["wal_bytes"] = wal_path.stat().st_size if wal_path.exists() else 0
    return snapshot


def _configure_sqlite_connection(
    dbapi_connection,
    _connection_record,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(
            f"PRAGMA wal_autocheckpoint={SQLITE_WAL_AUTOCHECKPOINT_PAGES}"
        )
    finally:
        cursor.close()
