from __future__ import annotations

import threading
import time
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlmodel import Session

from app.api import datasets, samples
from app.core import migrations
from app.core.database import create_legacy_baseline_tables, get_session
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.schemas.thumbnail import ThumbnailJobRequest
from app.services import job_service, thumbnail_job_service, thumbnail_service
from app.services.job_runner import JobRunner
from app.utils.hashing import sha256_file


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


def _create_image_sample(
    session: Session,
    dataset_id: int,
    root: Path,
    filename: str,
    color: tuple[int, int, int],
) -> Sample:
    path = root / filename
    Image.new("RGB", (120, 80), color).save(path, format="PNG")
    stat = path.stat()
    sample = Sample(
        dataset_id=dataset_id,
        filename=filename,
        absolute_path=str(path.resolve()),
        relative_path=filename,
        file_size=stat.st_size,
        extension=".png",
        file_type="image",
        mime_type="image/png",
        file_hash=sha256_file(path),
        file_status="normal",
        file_modified_at=thumbnail_service.utc_from_timestamp(stat.st_mtime),
    )
    session.add(sample)
    session.commit()
    session.refresh(sample)
    return sample


def _create_dataset_with_images(
    session: Session,
    root: Path,
    count: int,
) -> tuple[Dataset, list[Sample]]:
    root.mkdir()
    dataset = Dataset(name="Thumbnail dataset", root_path=str(root))
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    assert dataset.id is not None
    image_samples = [
        _create_image_sample(
            session,
            dataset.id,
            root,
            f"sample-{index}.png",
            (index * 20 % 255, 60, 120),
        )
        for index in range(count)
    ]
    return dataset, image_samples


def test_thumbnail_job_generates_hash_cache_and_serves_webp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "storage" / "thumbnails"
    monkeypatch.setattr(thumbnail_service, "thumbnail_cache_root", lambda: cache_root)
    engine = _migrated_engine(tmp_path / "thumbnail.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(
        thumbnail_job_service.THUMBNAIL_JOB_TYPE,
        thumbnail_job_service.run_thumbnail_job,
    )
    with Session(engine) as session:
        dataset, image_samples = _create_dataset_with_images(session, tmp_path / "raw", 2)
        assert dataset.id is not None
        dataset_id = dataset.id
        sample_ids = [sample.id for sample in image_samples if sample.id is not None]
        request = ThumbnailJobRequest(sample_ids=sample_ids)
        first = thumbnail_job_service.create_thumbnail_job(session, dataset.id, request)
        duplicate = thumbnail_job_service.create_thumbnail_job(session, dataset.id, request)
        first_sample_id = image_samples[0].id
        first_sample_hash = image_samples[0].file_hash
        assert first.created is True
        assert first.job is not None
        assert duplicate.created is False
        assert duplicate.job is not None
        assert duplicate.job.id == first.job.id

    before = {path.name: path.read_bytes() for path in (tmp_path / "raw").iterdir()}
    assert runner.start() is True
    completed = _wait_for_terminal(engine, first.job.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["requested_sample_count"] == 2
    assert completed.result["unique_content_count"] == 2
    assert completed.result["generated_count"] == 2
    assert completed.result["failed_count"] == 0
    assert completed.progress_current == 2
    assert completed.progress_total == 2

    app = FastAPI()
    app.include_router(samples.router)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        response = client.get(
            f"/api/samples/{first_sample_id}/thumbnail",
            params={"content_hash": first_sample_hash},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert "immutable" in response.headers["cache-control"]
        assert response.content[:4] == b"RIFF"
        assert response.content[8:12] == b"WEBP"

    with Session(engine) as session:
        cached = thumbnail_job_service.create_thumbnail_job(
            session,
            dataset_id,
            ThumbnailJobRequest(sample_ids=sample_ids),
        )
        assert cached.created is False
        assert cached.job is None
        assert cached.cached_count == 2

    assert runner.stop() is True
    assert {path.name: path.read_bytes() for path in (tmp_path / "raw").iterdir()} == before
    assert not list(cache_root.rglob("*.part"))
    engine.dispose()


def test_thumbnail_job_cancellation_preserves_cache_and_retry_converges(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "storage" / "thumbnails"
    monkeypatch.setattr(thumbnail_service, "thumbnail_cache_root", lambda: cache_root)
    entered = threading.Event()
    release = threading.Event()
    real_generate = thumbnail_service.generate_thumbnail

    def blocking_generate(candidate):
        entered.set()
        assert release.wait(timeout=3)
        return real_generate(candidate)

    monkeypatch.setattr(thumbnail_service, "generate_thumbnail", blocking_generate)
    engine = _migrated_engine(tmp_path / "thumbnail-cancel.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(
        thumbnail_job_service.THUMBNAIL_JOB_TYPE,
        thumbnail_job_service.run_thumbnail_job,
    )
    with Session(engine) as session:
        dataset, image_samples = _create_dataset_with_images(session, tmp_path / "raw", 4)
        assert dataset.id is not None
        created = thumbnail_job_service.create_thumbnail_job(
            session,
            dataset.id,
            ThumbnailJobRequest(
                sample_ids=[sample.id for sample in image_samples if sample.id is not None]
            ),
        )
        assert created.job is not None

    assert runner.start() is True
    assert entered.wait(timeout=3)
    with Session(engine) as session:
        job_service.request_job_cancel(session, created.job.id)
    release.set()
    cancelled = _wait_for_terminal(engine, created.job.id)
    assert cancelled.status == "cancelled"
    assert cancelled.result is not None
    assert cancelled.result["processed_content_count"] <= 2
    assert not list(cache_root.rglob("*.part"))

    with Session(engine) as session:
        retried = job_service.retry_job(session, created.job.id)
    runner.notify()
    completed = _wait_for_terminal(engine, retried.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["generated_count"] + completed.result["cached_count"] == 4
    assert runner.stop() is True
    engine.dispose()


def test_thumbnail_job_failure_can_be_retried(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "storage" / "thumbnails"
    monkeypatch.setattr(thumbnail_service, "thumbnail_cache_root", lambda: cache_root)
    engine = _migrated_engine(tmp_path / "thumbnail-retry.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(
        thumbnail_job_service.THUMBNAIL_JOB_TYPE,
        thumbnail_job_service.run_thumbnail_job,
    )
    with Session(engine) as session:
        dataset, image_samples = _create_dataset_with_images(session, tmp_path / "raw", 1)
        assert dataset.id is not None
        created = thumbnail_job_service.create_thumbnail_job(
            session,
            dataset.id,
            ThumbnailJobRequest(sample_ids=[image_samples[0].id]),
        )
        assert created.job is not None

    real_batch = thumbnail_service.generate_thumbnail_batch
    monkeypatch.setattr(
        thumbnail_service,
        "generate_thumbnail_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("storage unavailable")),
    )
    assert runner.start() is True
    failed = _wait_for_terminal(engine, created.job.id)
    assert failed.status == "failed"
    assert failed.error is not None
    assert "storage unavailable" in str(failed.error["message"])

    monkeypatch.setattr(thumbnail_service, "generate_thumbnail_batch", real_batch)
    with Session(engine) as session:
        retried = job_service.retry_job(session, created.job.id)
    runner.notify()
    completed = _wait_for_terminal(engine, retried.id)
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["generated_count"] == 1
    assert runner.stop() is True
    engine.dispose()


def test_thumbnail_api_rejects_stale_hash_and_unmigrated_job_creation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "storage" / "thumbnails"
    monkeypatch.setattr(thumbnail_service, "thumbnail_cache_root", lambda: cache_root)
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'thumbnail-legacy.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(engine)
    with Session(engine) as session:
        dataset, image_samples = _create_dataset_with_images(session, tmp_path / "raw", 1)
        assert dataset.id is not None
        dataset_id = dataset.id
        sample = image_samples[0]

    app = FastAPI()
    app.include_router(datasets.router)
    app.include_router(samples.router)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        create_response = client.post(
            f"/api/datasets/{dataset_id}/thumbnail-jobs",
            json={"sample_ids": [sample.id]},
        )
        assert create_response.status_code == 409

        missing = client.get(
            f"/api/samples/{sample.id}/thumbnail",
            params={"content_hash": sample.file_hash},
        )
        assert missing.status_code == 404

        stale = client.get(
            f"/api/samples/{sample.id}/thumbnail",
            params={"content_hash": sha256(b'stale').hexdigest()},
        )
        assert stale.status_code == 409
    engine.dispose()
