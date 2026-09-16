from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session

from app.api import jobs
from app.core import migrations
from app.core.database import get_session
from app.schemas.job import JobCreate
from app.services import job_service
from app.services.job_runner import JobContext, JobRunner


def _migrated_engine(database_path: Path):
    migrations.upgrade_database(database_path)
    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def _wait_for_status(engine, job_id: int, status: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session(engine) as session:
            job = job_service.get_job(session, job_id)
        if job.status == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach {status}.")


def test_runner_executes_registered_jobs_and_contains_failures(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path / "runner.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)

    def success_handler(
        context: JobContext,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        context.report_progress(current=1, total=1, stage="working")
        return {"echo": parameters["value"]}

    def oversized_result_handler(
        context: JobContext,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        return {"payload": "x" * job_service.MAX_JOB_JSON_BYTES}

    runner.register_handler("test.success", success_handler)
    runner.register_handler("test.oversized-result", oversized_result_handler)
    with Session(engine) as session:
        succeeded_source = job_service.create_job(
            session,
            JobCreate(
                job_type="test.success",
                title="Successful job",
                parameters={"value": "ok"},
                progress_total=1,
            ),
        )
        failed_source = job_service.create_job(
            session,
            JobCreate(job_type="test.unregistered", title="Missing handler"),
        )
        rejected_source = job_service.create_job(
            session,
            JobCreate(job_type="test.oversized-result", title="Oversized result"),
        )

    assert runner.start() is True
    succeeded = _wait_for_status(engine, succeeded_source.id, "succeeded")
    failed = _wait_for_status(engine, failed_source.id, "failed")
    rejected = _wait_for_status(engine, rejected_source.id, "failed")
    assert succeeded.progress_current == 1
    assert succeeded.result == {"echo": "ok"}
    assert failed.error is not None
    assert failed.error["code"] == "handler_not_registered"
    assert rejected.error is not None
    assert rejected.error["code"] == "result_rejected"
    assert runner.stop() is True
    engine.dispose()


def test_runner_cooperatively_cancels_and_interrupts(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path / "runner-cancel.db")
    entered = threading.Event()
    release = threading.Event()
    runner = JobRunner(engine, poll_interval_seconds=0.01)

    def cancellable_handler(
        context: JobContext,
        parameters: dict[str, object],
    ) -> None:
        entered.set()
        assert release.wait(timeout=2)
        context.checkpoint()

    runner.register_handler("test.cancel", cancellable_handler)
    with Session(engine) as session:
        source = job_service.create_job(
            session,
            JobCreate(job_type="test.cancel", title="Cancellable job"),
        )

    assert runner.start() is True
    assert entered.wait(timeout=2)
    with Session(engine) as session:
        requested = job_service.request_job_cancel(session, source.id)
        assert requested.status == "running"
    release.set()
    cancelled = _wait_for_status(engine, source.id, "cancelled")
    assert cancelled.error is not None
    assert cancelled.error["code"] == "cancel_requested"
    assert runner.stop() is True

    with Session(engine) as session:
        abandoned = job_service.create_job(
            session,
            JobCreate(job_type="test.cancel", title="Abandoned job"),
        )
        job_service.transition_job(session, abandoned.id, "running")
        assert job_service.interrupt_running_jobs(session) == 1
        interrupted = job_service.get_job(session, abandoned.id)
        assert interrupted.status == "interrupted"
        assert interrupted.error is not None
        assert interrupted.error["code"] == "process_restart"

    stop_entered = threading.Event()
    stop_runner = JobRunner(engine, poll_interval_seconds=0.01)

    def interruptible_handler(
        context: JobContext,
        parameters: dict[str, object],
    ) -> None:
        stop_entered.set()
        while True:
            time.sleep(0.01)
            context.checkpoint()

    stop_runner.register_handler("test.stop", interruptible_handler)
    with Session(engine) as session:
        stopping = job_service.create_job(
            session,
            JobCreate(job_type="test.stop", title="Interrupted on shutdown"),
        )
    assert stop_runner.start() is True
    assert stop_entered.wait(timeout=2)
    assert stop_runner.stop(timeout_seconds=2) is True
    stopped_job = _wait_for_status(engine, stopping.id, "interrupted")
    assert stopped_job.error is not None
    assert stopped_job.error["code"] == "runner_stopped"
    engine.dispose()


def test_job_mutation_api_create_cancel_and_retry(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path / "job-api.db")
    app = FastAPI()
    app.include_router(jobs.router)

    def test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    with TestClient(app) as client:
        created_response = client.post(
            "/api/jobs",
            json={"job_type": "test.api", "title": "API job"},
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["status"] == "queued"

        cancel_response = client.post(f"/api/jobs/{created['id']}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"

        retry_response = client.post(f"/api/jobs/{created['id']}/retry")
        assert retry_response.status_code == 201
        retried = retry_response.json()
        assert retried["status"] == "queued"
        assert retried["retry_of_id"] == created["id"]
        assert retried["attempt"] == 2
    engine.dispose()
