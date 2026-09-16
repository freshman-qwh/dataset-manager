from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session

from app.api import datasets
from app.core import migrations
from app.core.database import create_legacy_baseline_tables, get_session
from app.models.dataset import Dataset
from app.schemas.scan import ScanRequest
from app.services import job_service, scan_job_service, scan_service
from app.services.job_runner import JobRunner


def _migrated_engine(database_path: Path):
    migrations.upgrade_database(database_path)
    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def _wait_for_terminal(engine, job_id: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session(engine) as session:
            job = job_service.get_job(session, job_id)
        if job.status in job_service.TERMINAL_STATUSES:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach a terminal state.")


def _create_dataset(session: Session, root: Path) -> Dataset:
    dataset = Dataset(name="Scan job dataset", root_path=str(root))
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset


def test_scan_job_runs_incrementally_and_deduplicates_active_job(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    for index in range(5):
        (root / f"sample-{index}.jpg").write_bytes(str(index).encode())

    engine = _migrated_engine(tmp_path / "scan-job.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(scan_job_service.SCAN_JOB_TYPE, scan_job_service.run_scan_job)
    with Session(engine) as session:
        dataset = _create_dataset(session, root)
        assert dataset.id is not None
        dataset_id = dataset.id
        first = scan_job_service.create_scan_job(
            session,
            dataset_id,
            ScanRequest(folder_path=str(root)),
        )
        duplicate = scan_job_service.create_scan_job(
            session,
            dataset_id,
            ScanRequest(folder_path=str(root)),
        )
        assert first.created is True
        assert duplicate.created is False
        assert duplicate.job.id == first.job.id

    assert runner.start() is True
    completed = _wait_for_terminal(engine, first.job.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["imported"] == 5
    assert completed.result["hashed"] == 5
    assert completed.progress_current == 5
    assert completed.progress_total == 5

    with Session(engine) as session:
        second = scan_job_service.create_scan_job(
            session,
            dataset_id,
            ScanRequest(folder_path=str(root)),
        )
        assert second.created is True
        stored = session.get(Dataset, dataset_id)
        assert stored is not None
        assert stored.revision == 2
    runner.notify()
    rescanned = _wait_for_terminal(engine, second.job.id)
    assert rescanned.status == "succeeded"
    assert rescanned.result is not None
    assert rescanned.result["hashed"] == 0
    assert rescanned.result["hash_skipped_unchanged"] == 5
    with Session(engine) as session:
        stored = session.get(Dataset, dataset_id)
        assert stored is not None
        assert stored.revision == 2
    assert runner.stop() is True
    engine.dispose()


def test_scan_job_creation_is_atomic_for_concurrent_requests(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "sample.jpg").write_bytes(b"sample")
    engine = _migrated_engine(tmp_path / "concurrent-create.db")
    with Session(engine) as session:
        dataset = _create_dataset(session, root)
        assert dataset.id is not None
        dataset_id = dataset.id

    barrier = threading.Barrier(3)
    responses = []

    def create_job() -> None:
        with Session(engine) as session:
            barrier.wait()
            responses.append(
                scan_job_service.create_scan_job(
                    session,
                    dataset_id,
                    ScanRequest(folder_path=str(root)),
                )
            )

    threads = [threading.Thread(target=create_job) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()

    assert sorted(response.created for response in responses) == [False, True]
    assert len({response.job.id for response in responses}) == 1
    engine.dispose()


def test_scan_job_cancellation_keeps_partial_result_and_retry_converges(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    for index in range(101):
        (root / f"sample-{index:03}.jpg").write_bytes(str(index).encode())
    before = {path.name: path.read_bytes() for path in root.iterdir()}

    entered_hash = threading.Event()
    release_hash = threading.Event()
    real_hash = scan_service.sha256_file

    def blocking_hash(path: Path) -> str:
        entered_hash.set()
        assert release_hash.wait(timeout=3)
        return real_hash(path)

    monkeypatch.setattr(scan_service, "sha256_file", blocking_hash)
    engine = _migrated_engine(tmp_path / "cancel-scan.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(scan_job_service.SCAN_JOB_TYPE, scan_job_service.run_scan_job)
    with Session(engine) as session:
        dataset = _create_dataset(session, root)
        assert dataset.id is not None
        created = scan_job_service.create_scan_job(
            session,
            dataset.id,
            ScanRequest(folder_path=str(root)),
        )

    assert runner.start() is True
    assert entered_hash.wait(timeout=3)
    with Session(engine) as session:
        requested = job_service.request_job_cancel(session, created.job.id)
        assert requested.status == "running"
    release_hash.set()
    cancelled = _wait_for_terminal(engine, created.job.id)
    assert cancelled.status == "cancelled"
    assert cancelled.result is not None
    assert cancelled.result["imported"] == 100
    assert cancelled.result["batches_committed"] == 1

    with Session(engine) as session:
        retried = job_service.retry_job(session, created.job.id)
    runner.notify()
    completed = _wait_for_terminal(engine, retried.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["imported"] == 1
    assert completed.result["unchanged"] == 100
    assert runner.stop() is True
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    engine.dispose()


def test_scan_job_api_and_unmigrated_guard(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "sample.jpg").write_bytes(b"sample")
    migrated_engine = _migrated_engine(tmp_path / "scan-api.db")
    with Session(migrated_engine) as session:
        dataset = _create_dataset(session, root)
        assert dataset.id is not None
        dataset_id = dataset.id

    app = FastAPI()
    app.include_router(datasets.router)

    def migrated_session():
        with Session(migrated_engine) as session:
            yield session

    app.dependency_overrides[get_session] = migrated_session
    with TestClient(app) as client:
        first = client.post(
            f"/api/datasets/{dataset_id}/scan-jobs",
            json={"folder_path": str(root)},
        )
        assert first.status_code == 201
        assert first.json()["created"] is True
        duplicate = client.post(
            f"/api/datasets/{dataset_id}/scan-jobs",
            json={"folder_path": str(root)},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["created"] is False
        assert duplicate.json()["job"]["id"] == first.json()["job"]["id"]
    migrated_engine.dispose()

    unmigrated_engine = create_engine(
        f"sqlite:///{(tmp_path / 'unmigrated.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(unmigrated_engine)
    with Session(unmigrated_engine) as session:
        legacy_dataset = _create_dataset(session, root)
        assert legacy_dataset.id is not None
        legacy_dataset_id = legacy_dataset.id

    def unmigrated_session():
        with Session(unmigrated_engine) as session:
            yield session

    app.dependency_overrides[get_session] = unmigrated_session
    with TestClient(app) as client:
        response = client.post(
            f"/api/datasets/{legacy_dataset_id}/scan-jobs",
            json={"folder_path": str(root)},
        )
        assert response.status_code == 409
    unmigrated_engine.dispose()
