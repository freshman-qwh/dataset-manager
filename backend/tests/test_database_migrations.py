from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from app import models  # noqa: F401
from app.core import migrations


EXPECTED_TABLES = {
    "alembic_version",
    "annotation_classes",
    "annotations",
    "datasets",
    "sample_tag_links",
    "samples",
    "tags",
    "training_readiness_states",
}


def _table_names(database_path: Path) -> set[str]:
    with closing(sqlite3.connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def _create_unversioned_current_database(database_path: Path) -> None:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO datasets "
            "(id, name, task_type, auto_scan_on_open, created_at, updated_at) "
            "VALUES (1, 'legacy', 'detection', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO samples "
            "(id, dataset_id, filename, absolute_path, relative_path, file_size, "
            "extension, file_type, file_hash, file_status, annotation_progress, "
            "review_status, created_at, updated_at) "
            "VALUES (1, 1, 'sample.jpg', '/tmp/sample.jpg', 'sample.jpg', 1, "
            "'.jpg', 'image', 'hash', 'normal', 'not_started', 'not_reviewed', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    engine.dispose()


def test_upgrade_creates_fresh_database_at_head(tmp_path: Path) -> None:
    database_path = tmp_path / "fresh.db"

    result = migrations.upgrade_database(database_path)
    second_result = migrations.upgrade_database(database_path)

    assert result.changed is True
    assert result.backup is None
    assert result.current_revision == migrations.head_revision()
    assert second_result.changed is False
    assert second_result.backup is None
    assert EXPECTED_TABLES.issubset(_table_names(database_path))
    assert migrations.migration_status(database_path).needs_upgrade is False


def test_upgrade_adds_known_columns_to_legacy_table(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-columns.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "CREATE TABLE datasets ("
            "id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, "
            "description VARCHAR(2000), root_path VARCHAR(2000), "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        )
        connection.execute(
            "INSERT INTO datasets "
            "(id, name, created_at, updated_at) "
            "VALUES (1, 'legacy', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.commit()

    migrations.upgrade_database(database_path)

    with closing(sqlite3.connect(database_path)) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(datasets)").fetchall()
        }
        task_type = connection.execute(
            "SELECT task_type FROM datasets WHERE id = 1"
        ).fetchone()[0]
    assert {
        "task_type",
        "source",
        "modality",
        "license",
        "owner",
        "project",
        "notes",
        "auto_scan_on_open",
    }.issubset(columns)
    assert task_type == "detection"


def test_upgrade_backs_up_and_preserves_unversioned_database(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    backup_dir = tmp_path / "backups"
    _create_unversioned_current_database(database_path)

    result = migrations.upgrade_database(database_path, backup_dir)

    assert result.changed is True
    assert result.backup is not None
    backup_path = Path(result.backup.backup_path)
    assert backup_path.is_file()
    assert result.backup.quick_check == "ok"
    assert "alembic_version" not in _table_names(backup_path)
    assert migrations.current_revision(database_path) == migrations.head_revision()
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1


def test_failed_migration_leaves_original_database_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "legacy.db"
    _create_unversioned_current_database(database_path)
    original_bytes = database_path.read_bytes()

    def fail_upgrade(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(migrations.command, "upgrade", fail_upgrade)

    with pytest.raises(RuntimeError, match="injected migration failure"):
        migrations.upgrade_database(database_path, tmp_path / "backups")

    assert database_path.read_bytes() == original_bytes
    assert migrations.current_revision(database_path) is None
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1


def test_upgrade_refuses_database_with_sidecar(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    _create_unversioned_current_database(database_path)
    Path(f"{database_path}-wal").write_bytes(b"active")

    with pytest.raises(RuntimeError, match="stop the backend"):
        migrations.upgrade_database(database_path)

    assert migrations.current_revision(database_path) is None
