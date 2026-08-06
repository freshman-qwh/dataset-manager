from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session

from app.api import annotation_exports
from app.core import migrations
from app.core.database import create_legacy_baseline_tables, get_session
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.models.tag import Tag
from app.schemas.annotation import AnnotationReplaceRequest
from app.schemas.annotation_import import LabelmeImportJobCreateRequest, LabelmeImportRequest
from app.services import annotation_import_job_service, annotation_import_service, annotation_service, job_service
from app.services.job_runner import JobRunner


def _migrated_engine(database_path: Path):
    migrations.upgrade_database(database_path)
    return create_engine(f"sqlite:///{database_path.as_posix()}", connect_args={"check_same_thread": False})


def _wait_for_terminal(engine, job_id: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session(engine) as session:
            job = job_service.get_job(session, job_id)
        if job.status in job_service.TERMINAL_STATUSES:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach a terminal state.")


def _register_handlers(runner: JobRunner) -> None:
    runner.register_handler(
        annotation_import_job_service.LABELME_IMPORT_JOB_TYPE,
        annotation_import_job_service.run_labelme_import_job,
    )
    runner.register_handler(
        annotation_import_job_service.LABELME_IMPORT_ROLLBACK_JOB_TYPE,
        annotation_import_job_service.run_labelme_import_rollback_job,
    )


def _create_dataset(session: Session, root: Path, count: int) -> tuple[int, list[int]]:
    root.mkdir(parents=True)
    dataset = Dataset(name="LabelMe jobs", root_path=str(root))
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    assert dataset.id is not None
    original_tag = Tag(dataset_id=dataset.id, name="original-tag")
    session.add(original_tag)
    session.commit()
    session.refresh(original_tag)
    sample_ids: list[int] = []
    for index in range(count):
        path = root / f"sample-{index}.png"
        path.write_bytes(b"not-an-image")
        sample = Sample(
            dataset_id=dataset.id,
            filename=path.name,
            absolute_path=str(path),
            relative_path=path.name,
            file_size=path.stat().st_size,
            extension=".png",
            file_type="image",
            file_hash=f"hash-{index}",
            annotation_progress="completed_with_objects",
            review_status="approved",
            tags=[original_tag],
        )
        session.add(sample)
        session.commit()
        session.refresh(sample)
        assert sample.id is not None
        annotation_service.replace_sample_annotations(
            session,
            sample.id,
            AnnotationReplaceRequest(
                annotations=[{"label": "original", "shape_type": "point", "points": [0, 0]}],
                save_mode="complete",
                review_status="approved",
            ),
        )
        sample_ids.append(sample.id)
    return dataset.id, sample_ids


def _write_labelme_directory(root: Path, count: int) -> None:
    root.mkdir()
    for index in range(count):
        (root / f"sample-{index}.json").write_text(
            json.dumps({
                "version": "5.0.0",
                "shapes": [{"label": f"imported-{index}", "shape_type": "point", "points": [[1, 1]]}],
                "imagePath": f"sample-{index}.png",
            }),
            encoding="utf-8",
        )


def _preview(session: Session, dataset_id: int, source: Path):
    return annotation_import_service.prepare_labelme_import(
        session,
        dataset_id,
        LabelmeImportRequest(path=str(source), mode="directory", strategy="append", dry_run=True),
    )


def test_labelme_import_job_retry_is_idempotent_and_rollback_restores_annotations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recovery_root = tmp_path / "recovery"
    monkeypatch.setattr(
        annotation_import_job_service,
        "_journal_path",
        lambda job_id: recovery_root / f"job-{job_id}" / "rollback.jsonl",
    )
    monkeypatch.setattr(annotation_import_job_service, "IMPORT_BATCH_SIZE", 1)
    real_replace = annotation_import_job_service.annotation_service.replace_sample_annotations
    calls = 0

    def fail_second_replace(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated LabelMe batch failure")
        return real_replace(*args, **kwargs)

    engine = _migrated_engine(tmp_path / "labelme-job.db")
    source = tmp_path / "labelme"
    _write_labelme_directory(source, 3)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    _register_handlers(runner)
    with Session(engine) as session:
        dataset_id, sample_ids = _create_dataset(session, tmp_path / "raw", 3)
        monkeypatch.setattr(
            annotation_import_job_service.annotation_service,
            "replace_sample_annotations",
            fail_second_replace,
        )
        plan = _preview(session, dataset_id, source)
        created = annotation_import_job_service.create_labelme_import_job(
            session,
            dataset_id,
            LabelmeImportJobCreateRequest(
                path=str(source),
                mode="directory",
                strategy="append",
                sync_sample_tags=True,
                expected_source_sha256=plan.source_sha256,
                expected_plan_fingerprint=plan.plan_fingerprint,
            ),
        )
        duplicate = annotation_import_job_service.create_labelme_import_job(
            session,
            dataset_id,
            LabelmeImportJobCreateRequest(
                path=str(source),
                mode="directory",
                strategy="append",
                sync_sample_tags=True,
                expected_source_sha256=plan.source_sha256,
                expected_plan_fingerprint=plan.plan_fingerprint,
            ),
        )
        assert duplicate.created is False
        assert duplicate.job.id == created.job.id

    assert runner.start() is True
    failed = _wait_for_terminal(engine, created.job.id)
    assert failed.status == "failed"
    assert failed.result is not None
    assert failed.result["imported_samples"] == 1
    assert failed.result["rollback_available"] is True
    with Session(engine) as session:
        retried = job_service.retry_job(session, failed.id)
    runner.notify()
    completed = _wait_for_terminal(engine, retried.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["source_job_id"] == created.job.id
    with Session(engine) as session:
        for index, sample_id in enumerate(sample_ids):
            annotations = annotation_service.list_sample_annotations(session, sample_id)
            assert [item.label for item in annotations] == ["original", f"imported-{index}"]
            sample = session.get(Sample, sample_id)
            assert sample is not None
            session.refresh(sample, attribute_names=["tags"])
            assert {tag.name for tag in sample.tags} == {"original-tag", "original", f"imported-{index}"}
        rollback = annotation_import_job_service.create_labelme_import_rollback_job(session, completed.id)
    runner.notify()
    rolled_back = _wait_for_terminal(engine, rollback.job.id)
    assert rolled_back.status == "succeeded"
    with Session(engine) as session:
        for sample_id in sample_ids:
            annotations = annotation_service.list_sample_annotations(session, sample_id)
            assert [item.label for item in annotations] == ["original"]
            sample = session.get(Sample, sample_id)
            assert sample is not None
            assert sample.annotation_progress == "completed_with_objects"
            assert sample.review_status == "approved"
            session.refresh(sample, attribute_names=["tags"])
            assert [tag.name for tag in sample.tags] == ["original-tag"]
    assert sorted(path.name for path in (tmp_path / "raw").iterdir()) == [
        "sample-0.png",
        "sample-1.png",
        "sample-2.png",
    ]
    assert runner.stop() is True
    engine.dispose()


def test_labelme_import_job_rechecks_directory_and_legacy_api_is_guarded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        annotation_import_job_service,
        "_journal_path",
        lambda job_id: tmp_path / "recovery" / f"job-{job_id}" / "rollback.jsonl",
    )
    engine = _migrated_engine(tmp_path / "changed-source.db")
    source = tmp_path / "labelme"
    _write_labelme_directory(source, 1)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    _register_handlers(runner)
    with Session(engine) as session:
        dataset_id, sample_ids = _create_dataset(session, tmp_path / "raw", 1)
        plan = _preview(session, dataset_id, source)
        created = annotation_import_job_service.create_labelme_import_job(
            session,
            dataset_id,
            LabelmeImportJobCreateRequest(
                path=str(source),
                mode="directory",
                strategy="append",
                expected_source_sha256=plan.source_sha256,
                expected_plan_fingerprint=plan.plan_fingerprint,
            ),
        )
    (source / "sample-0.json").write_text("{}", encoding="utf-8")
    assert runner.start() is True
    failed = _wait_for_terminal(engine, created.job.id)
    assert failed.status == "failed"
    assert "changed after preview" in str(failed.error)
    with Session(engine) as session:
        assert [item.label for item in annotation_service.list_sample_annotations(session, sample_ids[0])] == ["original"]
    assert runner.stop() is True
    engine.dispose()

    legacy_engine = create_engine(
        f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(legacy_engine)
    with Session(legacy_engine) as session:
        dataset = Dataset(name="Legacy", root_path=str(tmp_path / "raw"))
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        assert dataset.id is not None
        legacy_dataset_id = dataset.id
    app = FastAPI()
    app.include_router(annotation_exports.router)

    def legacy_session():
        with Session(legacy_engine) as session:
            yield session

    app.dependency_overrides[get_session] = legacy_session
    with TestClient(app) as client:
        response = client.post(
            f"/api/datasets/{legacy_dataset_id}/annotation-import-labelme-jobs",
            json={
                "path": str(source),
                "mode": "directory",
                "expected_source_sha256": "0" * 64,
                "expected_plan_fingerprint": "0" * 64,
            },
        )
        assert response.status_code == 409
    legacy_engine.dispose()


def test_cancelled_labelme_import_keeps_partial_result_and_can_roll_back(tmp_path: Path, monkeypatch) -> None:
    recovery_root = tmp_path / "recovery"
    monkeypatch.setattr(
        annotation_import_job_service,
        "_journal_path",
        lambda job_id: recovery_root / f"job-{job_id}" / "rollback.jsonl",
    )
    monkeypatch.setattr(annotation_import_job_service, "IMPORT_BATCH_SIZE", 1)
    engine = _migrated_engine(tmp_path / "cancelled-labelme.db")
    source = tmp_path / "labelme-cancel"
    _write_labelme_directory(source, 3)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    _register_handlers(runner)
    entered_second_batch = threading.Event()
    release_second_batch = threading.Event()
    real_replace = annotation_import_job_service.annotation_service.replace_sample_annotations
    calls = 0

    def block_second_replace(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered_second_batch.set()
            assert release_second_batch.wait(timeout=3)
        return real_replace(*args, **kwargs)

    with Session(engine) as session:
        dataset_id, sample_ids = _create_dataset(session, tmp_path / "raw-cancel", 3)
        monkeypatch.setattr(
            annotation_import_job_service.annotation_service,
            "replace_sample_annotations",
            block_second_replace,
        )
        plan = _preview(session, dataset_id, source)
        created = annotation_import_job_service.create_labelme_import_job(
            session,
            dataset_id,
            LabelmeImportJobCreateRequest(
                path=str(source),
                mode="directory",
                strategy="append",
                expected_source_sha256=plan.source_sha256,
                expected_plan_fingerprint=plan.plan_fingerprint,
            ),
        )

    assert runner.start() is True
    assert entered_second_batch.wait(timeout=3)
    with Session(engine) as session:
        job_service.request_job_cancel(session, created.job.id)
    release_second_batch.set()
    cancelled = _wait_for_terminal(engine, created.job.id)
    assert cancelled.status == "cancelled"
    assert cancelled.result is not None
    assert cancelled.result["imported_samples"] == 2
    assert cancelled.result["rollback_available"] is True
    with Session(engine) as session:
        assert len(annotation_service.list_sample_annotations(session, sample_ids[0])) == 2
        assert len(annotation_service.list_sample_annotations(session, sample_ids[1])) == 2
        assert len(annotation_service.list_sample_annotations(session, sample_ids[2])) == 1
        rollback = annotation_import_job_service.create_labelme_import_rollback_job(session, cancelled.id)
    runner.notify()
    assert _wait_for_terminal(engine, rollback.job.id).status == "succeeded"
    with Session(engine) as session:
        for sample_id in sample_ids:
            assert [item.label for item in annotation_service.list_sample_annotations(session, sample_id)] == ["original"]
    assert runner.stop() is True
    engine.dispose()
