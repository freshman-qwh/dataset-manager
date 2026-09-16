from __future__ import annotations

import json
from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.core import migrations
from app.core.database import get_session
from app.main import app
from app.api import annotation_exports
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.schemas.annotation import AnnotationReplaceRequest
from app.schemas.annotation_import import AnnotationImportJobCreateRequest, AnnotationImportRequest
from app.services import annotation_import_job_service, annotation_import_service, annotation_service, job_service
from app.services.job_runner import JobRunner


def _client() -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _dataset(client: TestClient, root: Path, relative_paths: list[str]) -> tuple[int, list[dict]]:
    root.mkdir()
    for relative_path in relative_paths:
        image_path = root / relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 80), "white").save(image_path)
    dataset = client.post("/api/datasets", json={"name": "Format import", "root_path": str(root)}).json()
    assert client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(root)}).status_code == 200
    samples = client.get(f"/api/datasets/{dataset['id']}/samples", params={"page_size": 200, "sort_by": "relative_path"}).json()["items"]
    return dataset["id"], samples


def test_yolo_detection_and_segmentation_import_to_canvas_shapes(tmp_path: Path) -> None:
    with _client() as client:
        dataset_id, samples = _dataset(client, tmp_path / "images", ["nested/a.png"])
        sample_id = samples[0]["id"]
        source = tmp_path / "yolo"
        (source / "labels" / "nested").mkdir(parents=True)
        (source / "data.yaml").write_text("names:\n  0: defect\n", encoding="utf-8")
        label_file = source / "labels" / "nested" / "a.txt"
        label_file.write_text("0 0.5 0.5 0.4 0.5\n", encoding="utf-8")
        original_label_bytes = label_file.read_bytes()
        original_image_bytes = (tmp_path / "images" / "nested" / "a.png").read_bytes()

        preview = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "yolo_detection", "path": str(source), "mode": "directory", "dry_run": True,
        })
        assert preview.status_code == 200
        body = preview.json()
        assert body["format"] == "yolo_detection"
        assert body["created_annotations"] == 1
        applied = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "yolo_detection", "path": str(source), "mode": "directory",
            "expected_source_sha256": body["source_sha256"],
            "expected_plan_fingerprint": body["plan_fingerprint"],
        })
        assert applied.status_code == 200
        annotations = client.get(f"/api/samples/{sample_id}/annotations").json()
        assert annotations[0]["shape_type"] == "rectangle"
        assert annotations[0]["points"] == [30.0, 20.0, 70.0, 60.0]
        assert label_file.read_bytes() == original_label_bytes
        assert (tmp_path / "images" / "nested" / "a.png").read_bytes() == original_image_bytes

        label_file.write_text("0 0.1 0.1 0.9 0.1 0.5 0.8\n", encoding="utf-8")
        segmentation = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "yolo_segmentation", "path": str(source), "mode": "directory", "dry_run": False,
        })
        assert segmentation.status_code == 200
        annotations = client.get(f"/api/samples/{sample_id}/annotations").json()
        assert annotations[0]["shape_type"] == "polygon"
        assert annotations[0]["points"] == [10.0, 8.0, 90.0, 8.0, 50.0, 64.0]


def test_yolo_precheck_reports_unsupported_pose_and_bounds(tmp_path: Path) -> None:
    with _client() as client:
        dataset_id, samples = _dataset(client, tmp_path / "images", ["a.png"])
        sample_id = samples[0]["id"]
        assert client.put(f"/api/samples/{sample_id}/annotations", json={"annotations": [{"label": "keep", "shape_type": "point", "points": [1, 1]}]}).status_code == 200
        source = tmp_path / "yolo-invalid"
        (source / "labels").mkdir(parents=True)
        (source / "classes.txt").write_text("defect\n", encoding="utf-8")
        (source / "labels" / "a.txt").write_text("0 0.5 0.5 0.4 0.5 0.2\n0 1.2 0.5 0.4 0.5\n", encoding="utf-8")
        response = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "yolo_detection", "path": str(source), "mode": "directory", "dry_run": True,
        })
        assert response.status_code == 200
        codes = {item["code"] for item in response.json()["errors"]}
        assert {"UNSUPPORTED_YOLO_FORMAT", "COORDINATE_OUT_OF_BOUNDS", "NO_VALID_ANNOTATIONS"} <= codes
        assert response.json()["imported_samples"] == 0
        assert [item["label"] for item in client.get(f"/api/samples/{sample_id}/annotations").json()] == ["keep"]


def test_coco_import_bbox_polygon_and_structured_diagnostics(tmp_path: Path) -> None:
    with _client() as client:
        dataset_id, samples = _dataset(client, tmp_path / "images", ["a.png", "b.png"])
        sample_ids = {item["filename"]: item["id"] for item in samples}
        source = tmp_path / "coco.json"
        source.write_text(json.dumps({
            "images": [{"id": 1, "file_name": "a.png"}, {"id": 2, "file_name": "b.png"}],
            "categories": [{"id": 10, "name": "scratch"}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 10, "bbox": [10, 20, 30, 40]},
                {"id": 2, "image_id": 2, "category_id": 10, "segmentation": [[0, 0, 20, 0, 20, 20]]},
                {"id": 3, "image_id": 2, "category_id": 99, "bbox": [0, 0, 5, 5]},
                {"id": 4, "image_id": 2, "category_id": 10, "segmentation": {"counts": "RLE", "size": [80, 100]}, "bbox": [90, 70, 20, 20]},
            ],
        }), encoding="utf-8")
        original_source_bytes = source.read_bytes()
        preview = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "coco", "path": str(source), "mode": "file", "dry_run": True,
        })
        assert preview.status_code == 200
        result = preview.json()
        assert result["created_annotations"] == 2
        assert "UNSUPPORTED_RLE_MASK" in {item["code"] for item in result["warnings"]}
        assert {"COCO_CATEGORY_NOT_FOUND", "COORDINATE_OUT_OF_BOUNDS"} <= {item["code"] for item in result["errors"]}
        apply = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "coco", "path": str(source), "mode": "file",
            "expected_source_sha256": result["source_sha256"],
            "expected_plan_fingerprint": result["plan_fingerprint"],
        })
        assert apply.status_code == 200
        assert client.get(f"/api/samples/{sample_ids['a.png']}/annotations").json()[0]["points"] == [10.0, 20.0, 40.0, 60.0]
        assert client.get(f"/api/samples/{sample_ids['b.png']}/annotations").json()[0]["shape_type"] == "polygon"
        assert source.read_bytes() == original_source_bytes

        stale = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "coco", "path": str(source), "mode": "file", "expected_source_sha256": "0" * 64,
        })
        assert stale.status_code == 409


def test_coco_duplicate_images_are_blocked_from_plan(tmp_path: Path) -> None:
    with _client() as client:
        dataset_id, _ = _dataset(client, tmp_path / "images", ["a.png"])
        source = tmp_path / "duplicates.json"
        source.write_text(json.dumps({
            "images": [{"id": 1, "file_name": "a.png"}, {"id": 1, "file_name": "a.png"}],
            "categories": [{"id": 1, "name": "defect"}], "annotations": [],
        }), encoding="utf-8")
        result = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "coco", "path": str(source), "mode": "file", "dry_run": True,
        }).json()
        assert result["imported_samples"] == 0
        assert {"DUPLICATE_IMAGE_ID"} <= {item["code"] for item in result["errors"]}


def test_generic_yolo_job_and_rollback(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "jobs.db"
    migrations.upgrade_database(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(annotation_import_job_service, "_journal_path", lambda job_id: tmp_path / "recovery" / f"job-{job_id}" / "rollback.jsonl")
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    image_path = raw_root / "a.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    source = tmp_path / "yolo"
    (source / "labels").mkdir(parents=True)
    (source / "classes.txt").write_text("defect\n", encoding="utf-8")
    (source / "labels" / "a.txt").write_text("0 0.5 0.5 0.4 0.5\n", encoding="utf-8")
    with Session(engine) as session:
        dataset = Dataset(name="Generic jobs", root_path=str(raw_root))
        session.add(dataset); session.commit(); session.refresh(dataset)
        sample = Sample(dataset_id=dataset.id or 0, filename="a.png", absolute_path=str(image_path), relative_path="a.png", file_size=image_path.stat().st_size, extension=".png", file_type="image", file_hash="hash")
        session.add(sample); session.commit(); session.refresh(sample)
        annotation_service.replace_sample_annotations(session, sample.id or 0, AnnotationReplaceRequest(annotations=[{"label": "original", "shape_type": "point", "points": [1, 1]}]))
        preview = annotation_import_service.prepare_annotation_import(session, dataset.id or 0, AnnotationImportRequest(format="yolo_detection", path=str(source), mode="directory", dry_run=True))
        created = annotation_import_job_service.create_annotation_import_job(session, dataset.id or 0, AnnotationImportJobCreateRequest(
            format="yolo_detection", path=str(source), mode="directory", expected_source_sha256=preview.source_sha256, expected_plan_fingerprint=preview.plan_fingerprint,
        ))
        sample_id = sample.id or 0
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(annotation_import_job_service.ANNOTATION_IMPORT_JOB_TYPE, annotation_import_job_service.run_annotation_import_job)
    runner.register_handler(annotation_import_job_service.ANNOTATION_IMPORT_ROLLBACK_JOB_TYPE, annotation_import_job_service.run_annotation_import_rollback_job)
    assert runner.start()
    completed = _wait(engine, created.job.id)
    assert completed.status == "succeeded"
    with Session(engine) as session:
        assert annotation_service.list_sample_annotations(session, sample_id)[0].source == "yolo_detection"
        rollback = annotation_import_job_service.create_annotation_import_rollback_job(session, completed.id)
    runner.notify()
    assert _wait(engine, rollback.job.id).status == "succeeded"
    with Session(engine) as session:
        assert [item.label for item in annotation_service.list_sample_annotations(session, sample_id)] == ["original"]
    assert runner.stop()
    engine.dispose()


def test_generic_annotation_import_job_api_freezes_preview(tmp_path: Path) -> None:
    database_path = tmp_path / "job-api.db"
    migrations.upgrade_database(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}", connect_args={"check_same_thread": False})
    raw_root = tmp_path / "api-raw"
    raw_root.mkdir()
    image_path = raw_root / "a.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    source = tmp_path / "api-yolo"
    (source / "labels").mkdir(parents=True)
    (source / "classes.txt").write_text("defect\n", encoding="utf-8")
    (source / "labels" / "a.txt").write_text("0 0.5 0.5 0.4 0.5\n", encoding="utf-8")
    with Session(engine) as session:
        dataset = Dataset(name="Job API", root_path=str(raw_root))
        session.add(dataset); session.commit(); session.refresh(dataset)
        session.add(Sample(dataset_id=dataset.id or 0, filename="a.png", absolute_path=str(image_path), relative_path="a.png", file_size=image_path.stat().st_size, extension=".png", file_type="image", file_hash="hash"))
        session.commit()
        dataset_id = dataset.id or 0

    api = FastAPI()
    api.include_router(annotation_exports.router)

    def override_session():
        with Session(engine) as session:
            yield session

    api.dependency_overrides[get_session] = override_session
    with TestClient(api) as client:
        preview = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={
            "format": "yolo_detection", "path": str(source), "mode": "directory", "dry_run": True,
        }).json()
        created = client.post(f"/api/datasets/{dataset_id}/annotation-import-jobs", json={
            "format": "yolo_detection", "path": str(source), "mode": "directory",
            "expected_source_sha256": preview["source_sha256"],
            "expected_plan_fingerprint": preview["plan_fingerprint"],
        })
    assert created.status_code == 201
    body = created.json()
    assert body["job"]["job_type"] == "annotation.import"
    assert body["job"]["parameters"]["format"] == "yolo_detection"
    assert body["job"]["parameters"]["expected_plan_fingerprint"] == preview["plan_fingerprint"]
    engine.dispose()


def _wait(engine, job_id: int):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with Session(engine) as session:
            job = job_service.get_job(session, job_id)
        if job.status in job_service.TERMINAL_STATUSES:
            return job
        time.sleep(0.01)
    raise AssertionError("job timeout")
