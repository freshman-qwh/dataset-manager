import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session

from app.api import annotation_exports, datasets
from app.core.database import get_session
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.schemas.annotation import AnnotationReplaceRequest
from app.schemas.annotation_import import AnnotationImportConfirmRequest, AnnotationImportJobCreateRequest, AnnotationImportRequest
from app.services import annotation_import_service, annotation_import_job_service, annotation_import_review_service as review_service
from app.services import annotation_service, job_service
from app.services.job_runner import JobRunner
from test_annotation_import_labelme_jobs import _migrated_engine, _create_dataset, _wait_for_terminal
from test_annotation_import_formats import _client, _dataset


@pytest.fixture
def imported(tmp_path, monkeypatch):
    monkeypatch.setattr(annotation_import_job_service, "_journal_path", lambda job_id: tmp_path / "recovery" / str(job_id) / "rollback.jsonl")
    engine = _migrated_engine(tmp_path / "review.db")
    with Session(engine) as session:
        dataset_id, ids = _create_dataset(session, tmp_path / "raw", 6)
        for sample_id in ids:
            Image.new("RGB", (10, 10), "white").save(session.get(Sample, sample_id).absolute_path)
    source = tmp_path / "labels"
    source.mkdir()
    shape = {"label": "imported", "shape_type": "point", "points": [[1, 1]]}
    for index, shapes in enumerate([[shape], [], [shape, {"label": "ignored", "shape_type": "circle"}]]):
        (source / f"sample-{index}.json").write_text(json.dumps({"imagePath": f"sample-{index}.png", "shapes": shapes}), encoding="utf-8")
    (source / "sample-3.json").write_text(json.dumps({"imagePath": "sample-3.png"}), encoding="utf-8")
    (source / "missing.json").write_text(json.dumps({"imagePath": "missing.png", "shapes": []}), encoding="utf-8")
    return engine, dataset_id, ids, source


def run_import(imported, completion="draft", strategy="replace"):
    engine, dataset_id, ids, source = imported
    with Session(engine) as session:
        payload = AnnotationImportRequest(path=str(source), mode="directory", completion=completion, strategy=strategy, dry_run=True)
        preview = annotation_import_service.import_annotations(session, dataset_id, payload)
        job = annotation_import_job_service.create_annotation_import_job(session, dataset_id,
            AnnotationImportJobCreateRequest(**payload.model_dump(exclude={"dry_run", "expected_source_sha256", "expected_plan_fingerprint"}),
                expected_source_sha256=preview.source_sha256, expected_plan_fingerprint=preview.plan_fingerprint)).job
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(annotation_import_job_service.ANNOTATION_IMPORT_JOB_TYPE, annotation_import_job_service.run_annotation_import_job)
    runner.start()
    try:
        completed = _wait_for_terminal(engine, job.id)
        assert completed.status == "succeeded", completed.error
    finally:
        runner.stop()
    return job.id, preview


@pytest.mark.parametrize("completion", ["draft", "complete"])
def test_import_choice_and_exact_review_scope(imported, completion):
    engine, dataset_id, ids, _ = imported
    job_id, preview = run_import(imported, completion)
    assert preview.imported_samples == 3
    assert preview.planned_confirmed_samples == (2 if completion == "complete" else 0)
    with Session(engine) as session:
        assert review_service.review_sample_ids(session, dataset_id, job_id) == ids[:3]
        review = review_service.get_review(session, dataset_id, job_id)
        assert (review.completed, review.confirmable, review.needs_individual_review) == ((2, 0, 1) if completion == "complete" else (0, 2, 1))
        assert session.get(Sample, ids[0]).review_status == ("in_review" if completion == "complete" else "not_reviewed")
        assert session.get(Sample, ids[1]).annotation_progress == ("completed_empty" if completion == "complete" else "in_progress")
        assert session.get(Sample, ids[2]).annotation_progress == "in_progress"
        # Invalid/missing sources never become imported negatives; unrelated data remains intact.
        assert session.get(Sample, ids[3]).review_status == "approved"
        assert session.get(Sample, ids[5]).review_status == "approved"
        assert review_service.latest_review(session, dataset_id).job_id == job_id


def test_bulk_confirmation_preserves_objects_and_skips_individually_completed(imported):
    engine, dataset_id, ids, _ = imported
    job_id, _ = run_import(imported)
    with Session(engine) as session:
        objects = annotation_service.list_sample_annotations(session, ids[0])
        annotation_service.replace_sample_annotations(session, ids[0], AnnotationReplaceRequest(
            annotations=[annotation_import_service._annotation_read_to_create(item) for item in objects], save_mode="complete", review_status="approved"))
        object_ids = [item.id for item in annotation_service.list_sample_annotations(session, ids[0])]
        preview = review_service.get_review(session, dataset_id, job_id)
        revision = session.get(Dataset, dataset_id).revision
        result = review_service.confirm_remaining(session, dataset_id, job_id, AnnotationImportConfirmRequest(expected_fingerprint=preview.fingerprint))
        assert (result.completed, result.confirmable, result.needs_individual_review) == (2, 0, 1)
        assert session.get(Sample, ids[0]).review_status == "approved"
        assert [item.id for item in annotation_service.list_sample_annotations(session, ids[0])] == object_ids
        assert session.get(Sample, ids[1]).annotation_progress == "completed_empty"
        assert session.get(Sample, ids[2]).annotation_progress == "in_progress"
        assert session.get(Dataset, dataset_id).revision == revision + 1
        review_service.confirm_remaining(session, dataset_id, job_id, AnnotationImportConfirmRequest(expected_fingerprint=result.fingerprint))
        assert session.get(Dataset, dataset_id).revision == revision + 1


def test_modified_pending_content_and_stale_confirmation_are_protected(imported):
    engine, dataset_id, ids, _ = imported
    job_id, _ = run_import(imported)
    with Session(engine) as session:
        before = review_service.get_review(session, dataset_id, job_id)
        annotation_service.replace_sample_annotations(session, ids[0], AnnotationReplaceRequest(
            annotations=[{"label": "edited", "shape_type": "point", "points": [2, 2]}]))
        with pytest.raises(HTTPException) as failure:
            review_service.confirm_remaining(session, dataset_id, job_id, AnnotationImportConfirmRequest(expected_fingerprint=before.fingerprint))
        assert failure.value.status_code == 409
        assert session.get(Sample, ids[1]).annotation_progress == "in_progress"
        current = review_service.get_review(session, dataset_id, job_id)
        assert (current.confirmable, current.needs_individual_review) == (1, 2)
        review_service.confirm_remaining(session, dataset_id, job_id, AnnotationImportConfirmRequest(expected_fingerprint=current.fingerprint))
        assert session.get(Sample, ids[0]).annotation_progress == "in_progress"
        assert annotation_service.list_sample_annotations(session, ids[0])[0].label == "edited"


def test_review_navigation_api_and_wrong_dataset(imported):
    engine, dataset_id, ids, _ = imported
    job_id, _ = run_import(imported)
    app = FastAPI()
    app.include_router(annotation_exports.router)
    app.include_router(datasets.router)
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    with TestClient(app) as client:
        result = client.get(f"/api/datasets/{dataset_id}/samples/navigation", params={"import_job_id": job_id, "target_index": 3, "sort_by": "filename", "sort_order": "asc", "queue_scope": "all_pending"})
        assert result.status_code == 200, result.text
        assert result.json()["total"] == 3
        assert result.json()["current_sample"]["id"] == ids[2]
        wrong = client.get(f"/api/datasets/{dataset_id + 1}/annotation-import-jobs/{job_id}/review")
        assert wrong.status_code == 404
        response = client.get(f"/api/datasets/{dataset_id}/annotation-import-jobs/{job_id}/review")
        confirmed = client.post(f"/api/datasets/{dataset_id}/annotation-import-jobs/{job_id}/confirm", json={"expected_fingerprint": response.json()["fingerprint"]})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["completed"] == 2


def test_completion_choice_is_bound_to_preview(imported):
    engine, dataset_id, _, source = imported
    with Session(engine) as session:
        draft = annotation_import_service.import_annotations(session, dataset_id, AnnotationImportRequest(path=str(source), mode="directory", dry_run=True))
        with pytest.raises(job_service.JobStateError):
            annotation_import_job_service.create_annotation_import_job(session, dataset_id,
                AnnotationImportJobCreateRequest(path=str(source), mode="directory", completion="complete",
                    expected_source_sha256=draft.source_sha256, expected_plan_fingerprint=draft.plan_fingerprint))


def test_rollback_invalidates_review_and_restores_old_approval(imported):
    engine, dataset_id, ids, _ = imported
    job_id, _ = run_import(imported, "complete")
    with Session(engine) as session:
        rollback = annotation_import_job_service.create_annotation_import_rollback_job(session, job_id).job
        with pytest.raises(HTTPException):
            review_service.get_review(session, dataset_id, job_id)
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(annotation_import_job_service.ANNOTATION_IMPORT_ROLLBACK_JOB_TYPE, annotation_import_job_service.run_annotation_import_rollback_job)
    runner.start()
    try:
        assert _wait_for_terminal(engine, rollback.id).status == "succeeded"
    finally:
        runner.stop()
    with Session(engine) as session:
        assert review_service.latest_review(session, dataset_id) is None
        assert session.get(Sample, ids[0]).review_status == "approved"
        assert annotation_service.list_sample_annotations(session, ids[0])[0].label == "original"


@pytest.mark.parametrize("import_format", ["yolo_detection", "yolo_segmentation", "coco"])
def test_confirmed_import_supports_objects_and_genuine_empty_for_all_formats(tmp_path: Path, import_format):
    with _client() as client:
        dataset_id, samples = _dataset(client, tmp_path / "images", ["a.png", "b.png"])
        sample_ids = {sample["filename"]: sample["id"] for sample in samples}
        if import_format == "coco":
            source = tmp_path / "coco.json"
            source.write_text(json.dumps({"images": [{"id": 1, "file_name": "a.png"}, {"id": 2, "file_name": "b.png"}],
                "categories": [{"id": 1, "name": "defect"}],
                "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 20, 20]}]}), encoding="utf-8")
        else:
            source = tmp_path / "yolo"
            (source / "labels").mkdir(parents=True)
            (source / "classes.txt").write_text("defect\n", encoding="utf-8")
            (source / "labels" / "a.txt").write_text("0 0.5 0.5 0.4 0.5\n" if import_format == "yolo_detection" else "0 0.1 0.1 0.9 0.1 0.5 0.8\n", encoding="utf-8")
            (source / "labels" / "b.txt").write_text("", encoding="utf-8")
        request = {"format": import_format, "path": str(source), "mode": "file" if import_format == "coco" else "directory", "completion": "complete"}
        preview = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={**request, "dry_run": True}).json()
        assert preview["planned_confirmed_samples"] == 2
        result = client.post(f"/api/datasets/{dataset_id}/annotations/import", json={**request,
            "expected_source_sha256": preview["source_sha256"], "expected_plan_fingerprint": preview["plan_fingerprint"]})
        assert result.status_code == 200, result.text
        assert client.get(f"/api/samples/{sample_ids['a.png']}").json()["annotation_progress"] == "completed_with_objects"
        assert client.get(f"/api/samples/{sample_ids['b.png']}").json()["annotation_progress"] == "completed_empty"
