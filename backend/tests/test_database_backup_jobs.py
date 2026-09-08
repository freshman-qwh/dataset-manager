from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session

from app.api import jobs, system
from app.core import migrations
from app.core.database import create_legacy_baseline_tables, get_session
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.services import database_backup_service, job_artifact_service, job_service
from app.services.job_runner import JobRunner


def _migrated_engine(database_path: Path):
    migrations.upgrade_database(database_path)
    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def _test_app(engine) -> FastAPI:
    app = FastAPI()
    app.include_router(system.router)
    app.include_router(jobs.router)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return app


def _configure_paths(
    monkeypatch,
    *,
    database_path: Path,
    storage_root: Path,
) -> Path:
    artifact_root = storage_root / "job-artifacts"
    settings = SimpleNamespace(
        database_path=database_path,
        storage_root=storage_root,
    )
    monkeypatch.setattr(database_backup_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        job_artifact_service,
        "job_artifact_root",
        lambda: artifact_root,
    )
    return artifact_root


def _add_raw_sample(engine, raw_root: Path) -> dict[str, bytes]:
    raw_root.mkdir(parents=True)
    raw_file = raw_root / "sample.jpg"
    raw_file.write_bytes(b"raw-image-content")
    with Session(engine) as session:
        dataset = Dataset(name="backup dataset", root_path=str(raw_root))
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        assert dataset.id is not None
        session.add(
            Sample(
                dataset_id=dataset.id,
                filename=raw_file.name,
                absolute_path=str(raw_file),
                relative_path=raw_file.name,
                file_size=raw_file.stat().st_size,
                extension=".jpg",
                file_type="image",
                mime_type="image/jpeg",
                file_hash="a" * 64,
                file_status="normal",
            )
        )
        session.commit()
    return {path.name: path.read_bytes() for path in raw_root.iterdir()}


def test_backup_job_creates_verified_downloadable_sqlite_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "metadata.db"
    storage_root = tmp_path / "storage"
    raw_root = tmp_path / "raw"
    engine = _migrated_engine(database_path)
    artifact_root = _configure_paths(
        monkeypatch,
        database_path=database_path,
        storage_root=storage_root,
    )
    raw_before = _add_raw_sample(engine, raw_root)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(
        database_backup_service.DATABASE_BACKUP_JOB_TYPE,
        database_backup_service.run_database_backup_job,
    )

    with TestClient(_test_app(engine)) as client:
        created_response = client.post("/api/system/database-backup-jobs")
        duplicate_response = client.post("/api/system/database-backup-jobs")
        assert created_response.status_code == 201
        assert duplicate_response.status_code == 200
        created = created_response.json()
        assert duplicate_response.json()["job"]["id"] == created["job"]["id"]
        assert created["job"]["parameters"]["raw_files_included"] is False

        assert runner.run_once() is True
        job_id = int(created["job"]["id"])
        completed = client.get(f"/api/jobs/{job_id}").json()
        assert completed["status"] == "succeeded"
        assert completed["result"]["raw_files_included"] is False
        verification = completed["result"]["verification"]
        assert verification["quick_check"] == "ok"
        assert verification["foreign_key_violation_count"] == 0
        assert verification["current_revision"] == migrations.head_revision()
        assert verification["table_counts"]["datasets"] == 1
        assert verification["table_counts"]["samples"] == 1

        artifact = completed["result"]["artifact"]
        backup_path = artifact_root / f"job-{job_id}" / artifact["filename"]
        assert backup_path.is_file()
        assert artifact["size_bytes"] == backup_path.stat().st_size
        assert len(artifact["sha256"]) == 64
        with closing(sqlite3.connect(backup_path)) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1

        download = client.get(f"/api/jobs/{job_id}/artifact")
        assert download.status_code == 200
        assert download.content == backup_path.read_bytes()
        assert download.headers["content-type"].startswith("application/vnd.sqlite3")

    assert {path.name: path.read_bytes() for path in raw_root.iterdir()} == raw_before
    assert not list(raw_root.rglob("*.db"))
    assert not list(artifact_root.rglob("*.part"))
    engine.dispose()


def test_cancelled_backup_cleans_partial_file_and_can_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "cancel.db"
    storage_root = tmp_path / "storage"
    engine = _migrated_engine(database_path)
    artifact_root = _configure_paths(
        monkeypatch,
        database_path=database_path,
        storage_root=storage_root,
    )
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(
        database_backup_service.DATABASE_BACKUP_JOB_TYPE,
        database_backup_service.run_database_backup_job,
    )
    original_copy = database_backup_service._copy_database

    def cancel_copy(source_path: Path, target_path: Path, *, context) -> int:
        target_path.write_bytes(b"partial")
        with Session(context.engine) as session:
            job_service.request_job_cancel(session, context.job_id)
        context.checkpoint()
        return 1

    monkeypatch.setattr(database_backup_service, "_copy_database", cancel_copy)
    with TestClient(_test_app(engine)) as client:
        created = client.post("/api/system/database-backup-jobs").json()["job"]
        assert runner.run_once() is True
        cancelled = client.get(f"/api/jobs/{created['id']}").json()
        assert cancelled["status"] == "cancelled"
        assert not list(artifact_root.rglob("*.part"))
        assert not list(artifact_root.rglob("*.db"))

        monkeypatch.setattr(database_backup_service, "_copy_database", original_copy)
        retried = client.post(f"/api/jobs/{created['id']}/retry").json()
        assert retried["retry_of_id"] == created["id"]
        assert runner.run_once() is True
        completed = client.get(f"/api/jobs/{retried['id']}").json()
        assert completed["status"] == "succeeded"
        assert list(artifact_root.rglob("*.db"))
    engine.dispose()


def test_backup_failure_cleans_partial_output_and_legacy_db_returns_409(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "failure.db"
    storage_root = tmp_path / "storage"
    engine = _migrated_engine(database_path)
    artifact_root = _configure_paths(
        monkeypatch,
        database_path=database_path,
        storage_root=storage_root,
    )
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(
        database_backup_service.DATABASE_BACKUP_JOB_TYPE,
        database_backup_service.run_database_backup_job,
    )

    def fail_copy(_source_path: Path, target_path: Path, *, context) -> int:
        target_path.write_bytes(b"partial")
        raise OSError("simulated backup failure")

    monkeypatch.setattr(database_backup_service, "_copy_database", fail_copy)
    with TestClient(_test_app(engine)) as client:
        created = client.post("/api/system/database-backup-jobs").json()["job"]
        assert runner.run_once() is True
        failed = client.get(f"/api/jobs/{created['id']}").json()
        assert failed["status"] == "failed"
        assert "simulated backup failure" in failed["error"]["message"]
    assert not list(artifact_root.rglob("*.part"))
    assert not list(artifact_root.rglob("*.db"))
    engine.dispose()

    legacy_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(
        f"sqlite:///{legacy_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(legacy_engine)
    with TestClient(_test_app(legacy_engine)) as client:
        response = client.post("/api/system/database-backup-jobs")
    assert response.status_code == 409
    legacy_engine.dispose()
