from pathlib import Path

from sqlalchemy import inspect
from sqlmodel import create_engine

from app.core import database, migrations
from app.core.config import Settings


def test_fresh_startup_initializes_full_schema_without_upgrading_existing_database(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    settings = Settings(database_url=str(engine.url), database_path=path, storage_root=tmp_path / "storage")
    monkeypatch.setattr(database, "settings", settings)
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    assert migrations.current_revision(path) == migrations.head_revision()
    assert "jobs" in inspect(engine).get_table_names()
    assert "defect_types" in inspect(engine).get_table_names()
    engine.dispose()


def test_existing_unversioned_database_stays_on_explicit_upgrade_path(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    database.create_legacy_baseline_tables(engine)
    settings = Settings(database_url=str(engine.url), database_path=path, storage_root=tmp_path / "storage")
    monkeypatch.setattr(database, "settings", settings)
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    assert migrations.current_revision(path) is None
    assert "jobs" not in inspect(engine).get_table_names()
    engine.dispose()
