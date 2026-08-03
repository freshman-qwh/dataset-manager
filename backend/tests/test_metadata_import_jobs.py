from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session

from app.api import datasets
from app.core import migrations
from app.core.database import create_legacy_baseline_tables, get_session
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.models.tag import Tag
from app.schemas.metadata_import import MetadataImportJobCreateRequest
from app.services import job_service, metadata_import_job_service
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


def _create_dataset_with_samples(
    session: Session,
    root: Path,
    count: int,
) -> tuple[int, list[int]]:
    root.mkdir(parents=True)
    dataset = Dataset(name="Metadata jobs", root_path=str(root))
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    assert dataset.id is not None
    initial_tag = Tag(dataset_id=dataset.id, name="original")
    session.add(initial_tag)
    session.commit()
    session.refresh(initial_tag)

    samples = []
    for index in range(count):
        path = root / f"sample-{index:03}.jpg"
        path.write_bytes(str(index).encode("utf-8"))
        sample = Sample(
            dataset_id=dataset.id,
            filename=path.name,
            absolute_path=str(path),
            relative_path=path.name,
            file_size=path.stat().st_size,
            extension=".jpg",
            file_type="image",
            file_hash=f"hash-{index}",
            split="before",
            review_status="not_reviewed",
            notes="before",
            metadata_json=json.dumps({"quality": "before"}),
            tags=[initial_tag],
        )
        session.add(sample)
        samples.append(sample)
    session.commit()
    for sample in samples:
        session.refresh(sample)
        assert sample.id is not None
    return dataset.id, [sample.id for sample in samples if sample.id is not None]


def _write_metadata(path: Path, count: int) -> str:
    path.write_text(
        "relative_path,tags,split,review_status,notes,quality\n"
        + "".join(
            f"sample-{index:03}.jpg,imported,train,approved,after,after-{index}\n"
            for index in range(count)
        ),
        encoding="utf-8",
    )
    return sha256(path.read_bytes()).hexdigest()


def _register_handlers(runner: JobRunner) -> None:
    runner.register_handler(
        metadata_import_job_service.METADATA_IMPORT_JOB_TYPE,
        metadata_import_job_service.run_metadata_import_job,
    )
    runner.register_handler(
        metadata_import_job_service.METADATA_IMPORT_ROLLBACK_JOB_TYPE,
        metadata_import_job_service.run_metadata_import_rollback_job,
    )


def test_metadata_import_job_batches_deduplicates_and_rolls_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recovery_root = tmp_path / "recovery"
    monkeypatch.setattr(
        metadata_import_job_service,
        "_journal_path",
        lambda job_id: recovery_root / f"job-{job_id}" / "rollback.jsonl",
    )
    engine = _migrated_engine(tmp_path / "metadata-job.db")
    source = tmp_path / "metadata.csv"
    source_hash = _write_metadata(source, 3)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    _register_handlers(runner)

    with Session(engine) as session:
        dataset_id, sample_ids = _create_dataset_with_samples(
            session,
            tmp_path / "raw",
            3,
        )
        payload = MetadataImportJobCreateRequest(
            file_path=str(source),
            expected_source_sha256=source_hash,
            replace_tags=True,
        )
        created = metadata_import_job_service.create_metadata_import_job(
            session,
            dataset_id,
            payload,
        )
        duplicate = metadata_import_job_service.create_metadata_import_job(
            session,
            dataset_id,
            payload,
        )
        assert created.created is True
        assert duplicate.created is False
        assert duplicate.job.id == created.job.id

    assert runner.start() is True
    completed = _wait_for_terminal(engine, created.job.id)
    assert completed.status == "succeeded"
    assert completed.progress_current == 3
    assert completed.result == {
        "batches_committed": 1,
        "planned_updates": 3,
        "preview_error_count": 0,
        "rollback_available": True,
        "source_job_id": created.job.id,
        "source_sha256": source_hash,
        "unique_samples_changed": 3,
        "updated": 3,
    }
    assert (recovery_root / f"job-{created.job.id}" / "rollback.jsonl").is_file()
    assert sorted(path.name for path in (tmp_path / "raw").iterdir()) == [
        "sample-000.jpg",
        "sample-001.jpg",
        "sample-002.jpg",
    ]

    with Session(engine) as session:
        changed = session.get(Sample, sample_ids[0])
        assert changed is not None
        session.refresh(changed, attribute_names=["tags"])
        assert changed.split == "train"
        assert changed.review_status == "approved"
        assert changed.notes == "after"
        assert json.loads(changed.metadata_json or "{}") == {"quality": "after-0"}
        assert [tag.name for tag in changed.tags] == ["imported"]
        rollback = metadata_import_job_service.create_metadata_import_rollback_job(
            session,
            completed.id,
        )
        assert rollback.created is True
        duplicate_rollback = metadata_import_job_service.create_metadata_import_rollback_job(
            session,
            completed.id,
        )
        assert duplicate_rollback.created is False

    runner.notify()
    rolled_back = _wait_for_terminal(engine, rollback.job.id)
    assert rolled_back.status == "succeeded"
    assert rolled_back.result == {
        "batches_committed": 1,
        "missing": 0,
        "restored": 3,
        "source_job_id": created.job.id,
    }
    with Session(engine) as session:
        restored = session.get(Sample, sample_ids[0])
        assert restored is not None
        session.refresh(restored, attribute_names=["tags"])
        assert restored.split == "before"
        assert restored.review_status == "not_reviewed"
        assert restored.notes == "before"
        assert json.loads(restored.metadata_json or "{}") == {"quality": "before"}
        assert [tag.name for tag in restored.tags] == ["original"]
    assert runner.stop() is True
    engine.dispose()


def test_cancelled_metadata_import_retry_reuses_original_rollback_journal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recovery_root = tmp_path / "recovery"
    monkeypatch.setattr(
        metadata_import_job_service,
        "_journal_path",
        lambda job_id: recovery_root / f"job-{job_id}" / "rollback.jsonl",
    )
    monkeypatch.setattr(metadata_import_job_service, "IMPORT_BATCH_SIZE", 1)
    entered_apply = threading.Event()
    release_apply = threading.Event()
    real_apply = metadata_import_job_service.metadata_import_service.apply_metadata_row
    calls = 0

    def blocking_apply(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered_apply.set()
            assert release_apply.wait(timeout=3)
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(
        metadata_import_job_service.metadata_import_service,
        "apply_metadata_row",
        blocking_apply,
    )
    engine = _migrated_engine(tmp_path / "cancel-metadata.db")
    source = tmp_path / "metadata.csv"
    source_hash = _write_metadata(source, 3)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    _register_handlers(runner)
    with Session(engine) as session:
        dataset_id, sample_ids = _create_dataset_with_samples(
            session,
            tmp_path / "raw",
            3,
        )
        created = metadata_import_job_service.create_metadata_import_job(
            session,
            dataset_id,
            MetadataImportJobCreateRequest(
                file_path=str(source),
                expected_source_sha256=source_hash,
                replace_tags=True,
            ),
        )

    assert runner.start() is True
    assert entered_apply.wait(timeout=3)
    with Session(engine) as session:
        job_service.request_job_cancel(session, created.job.id)
    release_apply.set()
    cancelled = _wait_for_terminal(engine, created.job.id)
    assert cancelled.status == "cancelled"
    assert cancelled.result is not None
    assert cancelled.result["updated"] == 1
    assert cancelled.result["rollback_available"] is True

    with Session(engine) as session:
        retried = job_service.retry_job(session, cancelled.id)
    runner.notify()
    completed = _wait_for_terminal(engine, retried.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["source_job_id"] == created.job.id
    assert completed.result["unique_samples_changed"] == 3

    with Session(engine) as session:
        rollback = metadata_import_job_service.create_metadata_import_rollback_job(
            session,
            completed.id,
        )
    runner.notify()
    assert _wait_for_terminal(engine, rollback.job.id).status == "succeeded"
    with Session(engine) as session:
        for sample_id in sample_ids:
            sample = session.get(Sample, sample_id)
            assert sample is not None
            assert sample.split == "before"
            assert sample.review_status == "not_reviewed"
            assert sample.notes == "before"
    assert runner.stop() is True
    engine.dispose()


def test_metadata_import_job_rechecks_source_and_unmigrated_api_is_guarded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        metadata_import_job_service,
        "_journal_path",
        lambda job_id: tmp_path / "recovery" / f"job-{job_id}" / "rollback.jsonl",
    )
    source = tmp_path / "metadata.csv"
    source_hash = _write_metadata(source, 1)
    engine = _migrated_engine(tmp_path / "changed-source.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    _register_handlers(runner)
    with Session(engine) as session:
        dataset_id, sample_ids = _create_dataset_with_samples(
            session,
            tmp_path / "raw",
            1,
        )
        created = metadata_import_job_service.create_metadata_import_job(
            session,
            dataset_id,
            MetadataImportJobCreateRequest(
                file_path=str(source),
                expected_source_sha256=source_hash,
            ),
        )
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert runner.start() is True
    failed = _wait_for_terminal(engine, created.job.id)
    assert failed.status == "failed"
    assert "changed after preview" in str(failed.error)
    with Session(engine) as session:
        sample = session.get(Sample, sample_ids[0])
        assert sample is not None
        assert sample.split == "before"
    assert runner.stop() is True
    engine.dispose()

    legacy_engine = create_engine(
        f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(legacy_engine)
    with Session(legacy_engine) as session:
        legacy_dataset = Dataset(name="Legacy", root_path=str(tmp_path / "raw"))
        session.add(legacy_dataset)
        session.commit()
        session.refresh(legacy_dataset)
        assert legacy_dataset.id is not None
        legacy_dataset_id = legacy_dataset.id

    app = FastAPI()
    app.include_router(datasets.router)

    def legacy_session():
        with Session(legacy_engine) as session:
            yield session

    app.dependency_overrides[get_session] = legacy_session
    with TestClient(app) as client:
        response = client.post(
            f"/api/datasets/{legacy_dataset_id}/metadata-import-jobs",
            json={
                "file_path": str(source),
                "expected_source_sha256": sha256(source.read_bytes()).hexdigest(),
            },
        )
        assert response.status_code == 409
    legacy_engine.dispose()


def test_failed_metadata_import_retains_recovery_and_retry_converges(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recovery_root = tmp_path / "recovery"
    monkeypatch.setattr(
        metadata_import_job_service,
        "_journal_path",
        lambda job_id: recovery_root / f"job-{job_id}" / "rollback.jsonl",
    )
    monkeypatch.setattr(metadata_import_job_service, "IMPORT_BATCH_SIZE", 1)
    real_apply = metadata_import_job_service.metadata_import_service.apply_metadata_row
    calls = 0

    def fail_second_apply(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated metadata batch failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(
        metadata_import_job_service.metadata_import_service,
        "apply_metadata_row",
        fail_second_apply,
    )
    engine = _migrated_engine(tmp_path / "failed-metadata.db")
    source = tmp_path / "metadata.csv"
    source_hash = _write_metadata(source, 3)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    _register_handlers(runner)
    with Session(engine) as session:
        dataset_id, sample_ids = _create_dataset_with_samples(
            session,
            tmp_path / "raw",
            3,
        )
        created = metadata_import_job_service.create_metadata_import_job(
            session,
            dataset_id,
            MetadataImportJobCreateRequest(
                file_path=str(source),
                expected_source_sha256=source_hash,
                replace_tags=True,
            ),
        )

    assert runner.start() is True
    failed = _wait_for_terminal(engine, created.job.id)
    assert failed.status == "failed"
    assert failed.result is not None
    assert failed.result["updated"] == 1
    assert failed.result["batches_committed"] == 1
    assert failed.result["rollback_available"] is True
    assert failed.error is not None
    assert "simulated metadata batch failure" in str(failed.error["message"])

    with Session(engine) as session:
        retried = job_service.retry_job(session, failed.id)
    runner.notify()
    completed = _wait_for_terminal(engine, retried.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["source_job_id"] == created.job.id
    assert completed.result["unique_samples_changed"] == 3

    with Session(engine) as session:
        rollback = metadata_import_job_service.create_metadata_import_rollback_job(
            session,
            completed.id,
        )
    runner.notify()
    assert _wait_for_terminal(engine, rollback.job.id).status == "succeeded"
    with Session(engine) as session:
        for sample_id in sample_ids:
            sample = session.get(Sample, sample_id)
            assert sample is not None
            assert sample.split == "before"
            assert sample.review_status == "not_reviewed"
    assert runner.stop() is True
    engine.dispose()
