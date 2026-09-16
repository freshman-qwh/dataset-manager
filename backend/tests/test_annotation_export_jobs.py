from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
import threading
import time
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.api import annotation_exports, annotations, datasets, jobs, samples
from app.core.database import create_legacy_baseline_tables, get_session
from app.models.dataset import Dataset
from app.services import (
    annotation_export_job_service,
    annotation_export_service,
    job_artifact_service,
    job_service,
)
from app.services.job_runner import JobRunner


def _png_bytes(width: int = 32, height: int = 24) -> bytes:
    payload = bytearray(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00"
    )
    payload[16:24] = struct.pack(">II", width, height)
    return bytes(payload)


def _make_app(engine) -> FastAPI:
    app = FastAPI()
    app.include_router(datasets.router)
    app.include_router(samples.router)
    app.include_router(annotations.router)
    app.include_router(annotation_exports.router)
    app.include_router(jobs.router)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


def _create_export_dataset(
    client: TestClient,
    raw_root: Path,
    *,
    count: int = 2,
) -> int:
    raw_root.mkdir()
    for index in range(count):
        (raw_root / f"sample-{index:02}.png").write_bytes(
            _png_bytes() + bytes([index])
        )
    created = client.post(
        "/api/datasets",
        json={"name": "Async LabelMe", "root_path": str(raw_root)},
    )
    assert created.status_code == 201
    dataset_id = created.json()["id"]
    assert client.post(
        f"/api/datasets/{dataset_id}/scan",
        json={"folder_path": str(raw_root)},
    ).status_code == 200
    listed = client.get(
        f"/api/datasets/{dataset_id}/samples",
        params={"page_size": 200, "sort_by": "relative_path", "sort_order": "asc"},
    )
    assert listed.status_code == 200
    for index, sample in enumerate(listed.json()["items"]):
        assert client.patch(
            f"/api/samples/{sample['id']}",
            json={"split": "train" if index % 2 == 0 else "val"},
        ).status_code == 200
        saved = client.put(
            f"/api/samples/{sample['id']}/annotations",
            json={
                "annotations": [
                    {
                        "label": "object",
                        "shape_type": "rectangle",
                        "points": [1, 2, 10, 12],
                    }
                ]
            },
        )
        assert saved.status_code == 200
    return dataset_id


def _archive_contents(payload: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _wait_for_terminal(engine, job_id: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session(engine) as session:
            job = job_service.get_job(session, job_id)
        if job.status in job_service.TERMINAL_STATUSES:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach a terminal state.")


def test_coco_json_file_writer_preserves_bytes_and_checks_large_output(
    tmp_path: Path,
) -> None:
    payload = {
        "images": [
            {"id": index, "file_name": f"{index:05}-{'x' * 512}.png"}
            for index in range(2500)
        ]
    }
    destination = tmp_path / "large-coco.json"
    checkpoints: list[int] = []

    annotation_export_service._write_json_file(
        payload,
        destination,
        checkpoint=lambda: checkpoints.append(destination.stat().st_size),
    )

    expected = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    assert destination.read_bytes() == expected
    assert len(expected) > 1024 * 1024
    assert len(checkpoints) >= 2
    assert checkpoints[-1] == len(expected)


@pytest.mark.parametrize(
    ("export_format", "expected_media_type"),
    [
        ("labelme", "application/zip"),
        ("coco_detection", "application/json"),
        ("coco_segmentation", "application/json"),
        ("yolo_detection", "application/zip"),
        ("yolo_segmentation", "application/zip"),
        ("voc", "application/zip"),
    ],
)
def test_annotation_export_job_freezes_request_and_matches_sync_artifact(
    tmp_path: Path,
    monkeypatch,
    export_format: str,
    expected_media_type: str,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'export-job.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(
        job_artifact_service,
        "job_artifact_root",
        lambda: artifact_root,
    )
    app = _make_app(engine)
    raw_root = tmp_path / "raw"

    with TestClient(app) as client:
        dataset_id = _create_export_dataset(client, raw_root)
        before = {path.name: path.read_bytes() for path in raw_root.iterdir()}
        payload = {
            "format": export_format,
            "sample_query": {
                "sort_by": "relative_path",
                "sort_order": "asc",
            },
            "include_empty": False,
        }
        created = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-jobs",
            json=payload,
        )
        assert created.status_code == 201
        job = created.json()["job"]
        assert created.json()["created"] is True
        assert job["parameters"]["format"] == export_format
        assert job["parameters"]["class_map"][0]["name"] == "object"
        assert len(job["parameters"]["request_fingerprint"]) == 64

        duplicate = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-jobs",
            json=payload,
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["created"] is False
        assert duplicate.json()["job"]["id"] == job["id"]

        runner = JobRunner(engine)
        runner.register_handler(
            annotation_export_job_service.ANNOTATION_EXPORT_JOB_TYPE,
            annotation_export_job_service.run_annotation_export_job,
        )
        assert runner.run_once() is True
        completed = client.get(f"/api/jobs/{job['id']}").json()
        assert completed["status"] == "succeeded"
        artifact = completed["result"]["artifact"]
        assert artifact["size_bytes"] > 0
        assert len(artifact["sha256"]) == 64

        downloaded = client.get(f"/api/jobs/{job['id']}/artifact")
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].startswith(expected_media_type)
        assert sha256(downloaded.content).hexdigest() == artifact["sha256"]
        synchronous = client.get(
            f"/api/datasets/{dataset_id}/annotation-export",
            params={"format": export_format},
        )
        assert synchronous.status_code == 200
        if export_format not in {"coco_detection", "coco_segmentation"}:
            assert _archive_contents(downloaded.content) == _archive_contents(
                synchronous.content
            )
        else:
            assert downloaded.content == synchronous.content
        if export_format in {"yolo_detection", "yolo_segmentation"}:
            archive = _archive_contents(downloaded.content)
            assert "classes.txt" in archive
            assert "data.yaml" in archive
            assert "export_report.json" in archive
            assert "labels/train/sample-00.txt" in archive
            assert "labels/val/sample-01.txt" in archive
            assert f"task: {'detect' if export_format == 'yolo_detection' else 'segment'}" in archive[
                "data.yaml"
            ].decode("utf-8")
        if export_format == "voc":
            archive = _archive_contents(downloaded.content)
            assert "annotations/sample-00.xml" in archive
            assert "annotations/sample-01.xml" in archive
            assert "export_report.json" in archive
            artifact_path = job_artifact_service.resolve_job_artifact(
                artifact_root,
                job_id=job["id"],
                filename=artifact["filename"],
            )
            artifact_path.unlink()
            assert client.get(f"/api/jobs/{job['id']}/artifact").status_code == 410
        assert {path.name: path.read_bytes() for path in raw_root.iterdir()} == before
        assert not list(artifact_root.rglob("*.part"))

    engine.dispose()


@pytest.mark.parametrize(
    "export_format",
    [
        "labelme",
        "coco_detection",
        "coco_segmentation",
        "yolo_detection",
        "yolo_segmentation",
        "voc",
    ],
)
def test_cancelled_annotation_export_removes_partial_artifact(
    tmp_path: Path,
    monkeypatch,
    export_format: str,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'cancel-export.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(
        job_artifact_service,
        "job_artifact_root",
        lambda: artifact_root,
    )
    app = _make_app(engine)
    entered = threading.Event()
    release = threading.Event()

    with TestClient(app) as client:
        dataset_id = _create_export_dataset(client, tmp_path / "raw")
        created = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-jobs",
            json={"format": export_format},
        ).json()
        job_id = created["job"]["id"]

        def blocked_export(
            session,
            dataset_id,
            requested_format,
            destination,
            *,
            query,
            include_empty,
            checkpoint,
            progress,
        ):
            destination.write_bytes(b"partial archive")
            entered.set()
            assert release.wait(timeout=3)
            checkpoint()
            raise AssertionError("checkpoint should have cancelled the job")

        monkeypatch.setattr(
            annotation_export_service,
            "export_annotations_to_path",
            blocked_export,
        )
        runner = JobRunner(engine, poll_interval_seconds=0.01)
        runner.register_handler(
            annotation_export_job_service.ANNOTATION_EXPORT_JOB_TYPE,
            annotation_export_job_service.run_annotation_export_job,
        )
        assert runner.start() is True
        assert entered.wait(timeout=3)
        with Session(engine) as session:
            requested = job_service.request_job_cancel(session, job_id)
            assert requested.status == "running"
        release.set()
        cancelled = _wait_for_terminal(engine, job_id)
        assert cancelled.status == "cancelled"
        assert runner.stop() is True
        assert not (artifact_root / f"job-{job_id}").exists()

    engine.dispose()


@pytest.mark.parametrize(
    "export_format",
    [
        "labelme",
        "coco_detection",
        "coco_segmentation",
        "yolo_detection",
        "yolo_segmentation",
        "voc",
    ],
)
def test_annotation_export_job_failure_cleans_partial_artifact(
    tmp_path: Path,
    monkeypatch,
    export_format: str,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'failed-export.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(
        job_artifact_service,
        "job_artifact_root",
        lambda: artifact_root,
    )
    app = _make_app(engine)

    with TestClient(app) as client:
        dataset_id = _create_export_dataset(client, tmp_path / "raw")
        created = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-jobs",
            json={"format": export_format},
        ).json()
        job_id = created["job"]["id"]

        def failed_export(
            session,
            dataset_id,
            requested_format,
            destination,
            **kwargs,
        ):
            destination.write_bytes(b"partial archive")
            raise OSError("simulated disk failure")

        monkeypatch.setattr(
            annotation_export_service,
            "export_annotations_to_path",
            failed_export,
        )
        runner = JobRunner(engine)
        runner.register_handler(
            annotation_export_job_service.ANNOTATION_EXPORT_JOB_TYPE,
            annotation_export_job_service.run_annotation_export_job,
        )
        assert runner.run_once() is True
        failed = client.get(f"/api/jobs/{job_id}").json()
        assert failed["status"] == "failed"
        assert "simulated disk failure" in failed["error"]["message"]
        assert not (artifact_root / f"job-{job_id}").exists()
        unavailable = client.get(f"/api/jobs/{job_id}/artifact")
        assert unavailable.status_code == 409

    engine.dispose()


@pytest.mark.parametrize("export_format", ["yolo_detection", "voc"])
def test_export_job_retry_reuses_snapshot_and_publishes_artifact(
    tmp_path: Path,
    monkeypatch,
    export_format: str,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'retry-yolo.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(
        job_artifact_service,
        "job_artifact_root",
        lambda: artifact_root,
    )
    app = _make_app(engine)
    original_export = annotation_export_service.export_annotations_to_path

    with TestClient(app) as client:
        dataset_id = _create_export_dataset(client, tmp_path / "raw")
        created = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-jobs",
            json={
                "format": export_format,
                "sample_query": {
                    "split": "train",
                    "sort_by": "relative_path",
                    "sort_order": "asc",
                },
            },
        ).json()
        job_id = created["job"]["id"]

        def failed_export(*args, **kwargs):
            destination = args[3]
            destination.write_bytes(b"partial archive")
            raise OSError("simulated retryable failure")

        monkeypatch.setattr(
            annotation_export_service,
            "export_annotations_to_path",
            failed_export,
        )
        runner = JobRunner(engine)
        runner.register_handler(
            annotation_export_job_service.ANNOTATION_EXPORT_JOB_TYPE,
            annotation_export_job_service.run_annotation_export_job,
        )
        assert runner.run_once() is True
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"
        assert not (artifact_root / f"job-{job_id}").exists()

        monkeypatch.setattr(
            annotation_export_service,
            "export_annotations_to_path",
            original_export,
        )
        retried_response = client.post(f"/api/jobs/{job_id}/retry")
        assert retried_response.status_code == 201
        retried = retried_response.json()
        assert retried["retry_of_id"] == job_id
        assert retried["parameters"] == created["job"]["parameters"]
        assert runner.run_once() is True

        completed = client.get(f"/api/jobs/{retried['id']}").json()
        assert completed["status"] == "succeeded"
        downloaded = client.get(f"/api/jobs/{retried['id']}/artifact")
        assert downloaded.status_code == 200
        synchronous = client.get(
            f"/api/datasets/{dataset_id}/annotation-export",
            params={
                "format": export_format,
                "split": "train",
                "sort_by": "relative_path",
                "sort_order": "asc",
            },
        )
        assert synchronous.status_code == 200
        assert _archive_contents(downloaded.content) == _archive_contents(
            synchronous.content
        )

    engine.dispose()


@pytest.mark.parametrize(
    "export_format",
    [
        "labelme",
        "coco_detection",
        "coco_segmentation",
        "yolo_detection",
        "yolo_segmentation",
        "voc",
    ],
)
def test_annotation_export_job_rejects_unmigrated_database(
    tmp_path: Path,
    export_format: str,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Legacy export")
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        assert dataset.id is not None
        dataset_id = dataset.id

    with TestClient(_make_app(engine)) as client:
        response = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-jobs",
            json={"format": export_format},
        )
        assert response.status_code == 409

    engine.dispose()
