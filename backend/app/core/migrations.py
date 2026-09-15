from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_ROOT / "alembic.ini"
MIGRATIONS_PATH = BACKEND_ROOT / "migrations"


@dataclass(frozen=True)
class MigrationStatus:
    database_path: str
    exists: bool
    current_revision: str | None
    head_revision: str
    needs_upgrade: bool

    def to_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


@dataclass(frozen=True)
class BackupResult:
    source_path: str
    backup_path: str
    quick_check: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationResult:
    database_path: str
    previous_revision: str | None
    current_revision: str
    backup: BackupResult | None
    changed: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["backup"] = self.backup.to_dict() if self.backup else None
        return payload


def sqlite_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.resolve().as_posix()}"


def alembic_config(database_path: Path) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    config.set_main_option("sqlalchemy.url", sqlite_url(database_path).replace("%", "%%"))
    return config


def head_revision() -> str:
    revision = ScriptDirectory.from_config(
        alembic_config(BACKEND_ROOT / "database" / "app.db")
    ).get_current_head()
    if revision is None:
        raise RuntimeError("No Alembic head revision is configured.")
    return revision


def current_revision(database_path: Path) -> str | None:
    path = database_path.resolve()
    if not path.exists() or path.stat().st_size == 0:
        return None

    with closing(sqlite3.connect(path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'alembic_version'"
        ).fetchone()
        if table is None:
            return None
        row = connection.execute(
            "SELECT version_num FROM alembic_version LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else None


def migration_status(database_path: Path) -> MigrationStatus:
    path = database_path.resolve()
    current = current_revision(path)
    head = head_revision()
    return MigrationStatus(
        database_path=str(path),
        exists=path.exists(),
        current_revision=current,
        head_revision=head,
        needs_upgrade=current != head,
    )


def _quick_check(database_path: Path) -> str:
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute("PRAGMA quick_check").fetchone()
    result = str(row[0]) if row else "missing result"
    if result.lower() != "ok":
        raise RuntimeError(f"SQLite quick_check failed for {database_path}: {result}")
    return result


def create_verified_backup(
    database_path: Path,
    backup_dir: Path | None = None,
) -> BackupResult:
    source_path = database_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {source_path}")

    target_dir = (
        backup_dir.resolve()
        if backup_dir is not None
        else source_path.parent / "backups"
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = target_dir / f"{source_path.stem}-{timestamp}.db"

    with closing(
        sqlite3.connect(
            f"file:{source_path.as_posix()}?mode=ro",
            uri=True,
        )
    ) as source_connection:
        with closing(sqlite3.connect(backup_path)) as backup_connection:
            source_connection.backup(backup_connection)

    quick_check = _quick_check(backup_path)
    return BackupResult(
        source_path=str(source_path),
        backup_path=str(backup_path),
        quick_check=quick_check,
    )


def _has_user_tables(database_path: Path) -> bool:
    if not database_path.exists() or database_path.stat().st_size == 0:
        return False
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
    return row is not None


def _sidecar_paths(database_path: Path) -> list[Path]:
    return [
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
        Path(f"{database_path}-journal"),
    ]


def _ensure_database_is_offline(
    database_path: Path,
    *,
    reject_sidecars: bool = True,
) -> None:
    active = [str(path) for path in _sidecar_paths(database_path) if path.exists()]
    if reject_sidecars and active:
        raise RuntimeError(
            "Database sidecar files are present; stop the backend before migration. "
            f"Found: {', '.join(active)}"
        )

    if not database_path.exists():
        return
    try:
        with closing(sqlite3.connect(database_path, timeout=0)) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "Database is busy; stop the backend and retry the migration."
        ) from exc


def _checkpoint_database(database_path: Path) -> None:
    with closing(sqlite3.connect(database_path, timeout=0)) as connection:
        row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if row is not None and int(row[0]) != 0:
        raise RuntimeError(
            f"Could not checkpoint the migration database: {database_path}"
        )


def _remove_safe_sidecars(database_path: Path) -> None:
    wal_path = Path(f"{database_path}-wal")
    if wal_path.exists() and wal_path.stat().st_size > 0:
        raise RuntimeError(
            "Database WAL contains uncheckpointed data; the original database "
            "was preserved. Stop all database users and retry."
        )
    for sidecar_path in _sidecar_paths(database_path):
        if sidecar_path.exists():
            sidecar_path.unlink()


def recover_database_after_unclean_shutdown(database_path: Path) -> bool:
    """Recover a SQLite WAL only after the launcher owns the process mutex.

    Opening SQLite applies committed WAL records. A successful truncate
    checkpoint and quick_check prove that no WAL data is discarded before
    residual sidecar files are removed.
    """
    path = database_path.resolve()
    if not path.exists() or not any(sidecar.exists() for sidecar in _sidecar_paths(path)):
        return False
    _ensure_database_is_offline(path, reject_sidecars=False)
    _checkpoint_database(path)
    _quick_check(path)
    _remove_safe_sidecars(path)
    return True


def _cleanup_staging_files(staging_path: Path) -> None:
    for path in [staging_path, *_sidecar_paths(staging_path)]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Cleanup must not hide the migration error; all staging files are
            # isolated from the original database and ignored by Git.
            pass


def upgrade_database(
    database_path: Path,
    backup_dir: Path | None = None,
) -> MigrationResult:
    path = database_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_database_is_offline(path)
    previous = current_revision(path)
    head = head_revision()
    if previous == head:
        return MigrationResult(
            database_path=str(path),
            previous_revision=previous,
            current_revision=head,
            backup=None,
            changed=False,
        )

    backup = (
        create_verified_backup(path, backup_dir)
        if _has_user_tables(path)
        else None
    )
    staging_path = path.parent / f".{path.stem}.migration-{uuid4().hex}.db"

    try:
        if backup is not None:
            with closing(sqlite3.connect(backup.backup_path)) as source_connection:
                with closing(sqlite3.connect(staging_path)) as staging_connection:
                    source_connection.backup(staging_connection)

        command.upgrade(alembic_config(staging_path), "head")
        _checkpoint_database(staging_path)
        _quick_check(staging_path)
        migrated_revision = current_revision(staging_path)
        if migrated_revision != head:
            raise RuntimeError(
                "Migration finished without reaching the expected revision: "
                f"expected {head}, got {migrated_revision}."
            )

        _ensure_database_is_offline(path, reject_sidecars=False)
        _remove_safe_sidecars(path)
        os.replace(staging_path, path)
    finally:
        _cleanup_staging_files(staging_path)

    return MigrationResult(
        database_path=str(path),
        previous_revision=previous,
        current_revision=head,
        backup=backup,
        changed=True,
    )
