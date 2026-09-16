from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlmodel import Session, SQLModel

from app import models  # noqa: F401
from app.api import jobs
from app.core import migrations
from app.core.database import (
    LEGACY_BASELINE_TABLES,
    create_legacy_baseline_tables,
    get_session,
)
from app.models.dataset import Dataset
from app.schemas.job import JobCreate
from app.services import job_service


def _migrated_engine(database_path: Path):
    migrations.upgrade_database(database_path)
    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def test_legacy_startup_baseline_does_not_create_jobs(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-startup.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    create_legacy_baseline_tables(engine)

    table_names = set(inspect(engine).get_table_names())
    assert set(LEGACY_BASELINE_TABLES).issubset(table_names)
    assert "jobs" not in table_names
    engine.dispose()


def test_job_state_contract_progress_cancel_and_retry(tmp_path: Path) -> None:
    database_path = tmp_path / "jobs.db"
    engine = _migrated_engine(database_path)

    with Session(engine) as session:
        dataset = Dataset(name="jobs-dataset")
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        assert dataset.id is not None

        created = job_service.create_job(
            session,
            JobCreate(
                job_type="test.index",
                title="Build test index",
                dataset_id=dataset.id,
                parameters={"batch_size": 100},
                progress_total=10,
            ),
        )
        assert created.status == "queued"
        assert created.parameters == {"batch_size": 100}

        running = job_service.transition_job(
            session,
            created.id,
            "running",
            stage="enumerating",
        )
        assert running.started_at is not None
        progress = job_service.update_job_progress(
            session,
            created.id,
            current=4,
            total=10,
            stage="hashing",
            error_count=1,
        )
        assert progress.progress_current == 4
        assert progress.stage == "hashing"
        assert progress.error_count == 1

        cancel_requested = job_service.request_job_cancel(session, created.id)
        assert cancel_requested.status == "running"
        assert cancel_requested.cancel_requested_at is not None
        interrupted = job_service.transition_job(
            session,
            created.id,
            "interrupted",
            stage="process_stopped",
            error={"code": "process_restart"},
        )
        assert interrupted.finished_at is not None
        assert interrupted.error == {"code": "process_restart"}

        retried = job_service.retry_job(session, created.id)
        assert retried.status == "queued"
        assert retried.attempt == 2
        assert retried.retry_of_id == created.id
        assert retried.parameters == created.parameters

        cancelled = job_service.request_job_cancel(session, retried.id)
        assert cancelled.status == "cancelled"
        with pytest.raises(job_service.JobStateError):
            job_service.transition_job(session, retried.id, "running")
        with pytest.raises(job_service.JobStateError):
            job_service.update_job_progress(
                session,
                created.id,
                current=5,
            )

        listed = job_service.list_jobs(
            session,
            status="cancelled",
            dataset_id=dataset.id,
        )
        assert listed.total == 1
        assert listed.items[0].id == retried.id
    engine.dispose()


def test_job_json_snapshots_are_bounded(tmp_path: Path) -> None:
    database_path = tmp_path / "bounded-jobs.db"
    engine = _migrated_engine(database_path)

    with Session(engine) as session:
        with pytest.raises(job_service.JobStateError, match="cannot exceed"):
            job_service.create_job(
                session,
                JobCreate(
                    job_type="test.large-snapshot",
                    title="Reject an oversized snapshot",
                    parameters={"payload": "x" * job_service.MAX_JOB_JSON_BYTES},
                ),
            )
        created = job_service.create_job(
            session,
            JobCreate(job_type="test.transition-snapshot", title="Stay atomic"),
        )
        job_service.transition_job(session, created.id, "running")
        with pytest.raises(job_service.JobStateError, match="cannot exceed"):
            job_service.transition_job(
                session,
                created.id,
                "failed",
                error={"detail": "x" * job_service.MAX_JOB_JSON_BYTES},
            )
        session.expire_all()
        unchanged = job_service.get_job(session, created.id)
        assert unchanged.status == "running"
        assert unchanged.error is None
    engine.dispose()


def test_jobs_read_api_and_unmigrated_guard(tmp_path: Path) -> None:
    migrated_path = tmp_path / "migrated.db"
    migrated_engine = _migrated_engine(migrated_path)
    with Session(migrated_engine) as session:
        created = job_service.create_job(
            session,
            JobCreate(job_type="test.read", title="Read API"),
        )

    app = FastAPI()
    app.include_router(jobs.router)

    def migrated_session():
        with Session(migrated_engine) as session:
            yield session

    app.dependency_overrides[get_session] = migrated_session
    with TestClient(app) as client:
        list_response = client.get("/api/jobs")
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        detail_response = client.get(f"/api/jobs/{created.id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["title"] == "Read API"
        assert client.get("/api/jobs/999").status_code == 404
    migrated_engine.dispose()

    unmigrated_path = tmp_path / "unmigrated.db"
    unmigrated_engine = create_engine(
        f"sqlite:///{unmigrated_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(unmigrated_engine)

    def unmigrated_session():
        with Session(unmigrated_engine) as session:
            yield session

    app.dependency_overrides[get_session] = unmigrated_session
    with TestClient(app) as client:
        response = client.get("/api/jobs")
        assert response.status_code == 409
        assert "upgrade" in response.json()["detail"].lower()
    unmigrated_engine.dispose()
