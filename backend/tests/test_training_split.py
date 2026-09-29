from pathlib import Path
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from PIL import Image

from app.core.database import get_session
from app.main import app
from app.models.sample import Sample


def test_training_split_preview_commit_and_stale_rejection(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            created = client.post("/api/datasets", json={"name": "Training split", "root_path": str(tmp_path)})
            assert created.status_code == 201
            dataset_id = created.json()["id"]
            with Session(engine) as session:
                for name, hash_value, progress, split, triage in [
                    ("a.png", "same", "completed_with_objects", None, "ok"),
                    ("b.png", "same", "completed_empty", None, "ng"),
                    ("c.png", "other", "completed_with_objects", "val", "untriaged"),
                    ("d.png", "pending", "not_started", None, "ok"),
                ]:
                    session.add(Sample(
                        dataset_id=dataset_id, filename=name, relative_path=name,
                        absolute_path=str(tmp_path / name), file_type="image", extension=".png",
                        file_hash=hash_value, annotation_progress=progress,
                        split=split, triage_status=triage,
                    ))
                session.commit()
            base = f"/api/datasets/{dataset_id}/training-split"
            request = {"train_ratio": 80, "val_ratio": 20, "test_ratio": 0, "include_test": False}
            preview_response = client.post(f"{base}/preview", json=request)
            assert preview_response.status_code == 200
            preview = preview_response.json()
            assert preview["candidate_count"] == 3
            assert preview["excluded_counts"] == {"unfinished": 1}
            assert preview["unassigned_count"] == 2
            assert preview["duplicate_group_count"] == 1
            assert preview["split_counts"] == {"train": 2, "val": 1, "test": 0}
            assert preview["rows"][0]["suggested_split"] == preview["rows"][1]["suggested_split"]
            assert client.post(f"{base}/preview", json={**request, "triage_filter": "ok"}).json()["candidate_count"] == 0

            with Session(engine) as session:
                sample = session.exec(select(Sample).where(Sample.relative_path == "a.png")).one()
                sample.triaged_file_hash = sample.file_hash
                sample.triage_policy_version = 1
                session.add(sample)
                session.commit()
            assert client.post(f"{base}/preview", json={**request, "triage_filter": "ok"}).json()["candidate_count"] == 1

            with Session(engine) as session:
                sample = session.exec(select(Sample).where(Sample.relative_path == "a.png")).one()
                sample.review_status = "in_review"
                session.add(sample)
                session.commit()
            stale = client.post(f"{base}/commit", json={**request, "fingerprint": preview["fingerprint"]})
            assert stale.status_code == 409
            with Session(engine) as session:
                assert session.exec(select(Sample).where(Sample.relative_path == "b.png")).one().split is None

            refreshed = client.post(f"{base}/preview", json=request).json()
            committed = client.post(f"{base}/commit", json={**request, "fingerprint": refreshed["fingerprint"]})
            assert committed.status_code == 200
            assert committed.json()["updated"] == 2
            assert len(committed.json()["sample_ids"]) == 3
            assert committed.json()["dataset_revision"] > 1
            assert client.post(f"{base}/commit", json={**request, "fingerprint": refreshed["fingerprint"]}).json() == committed.json()
            stale_export = client.post(
                f"/api/datasets/{dataset_id}/annotation-export-precheck",
                json={"format": "yolo_detection", "include_images": True,
                      "sample_query": {"sample_ids": committed.json()["sample_ids"],
                                       "expected_dataset_revision": committed.json()["dataset_revision"] - 1}},
            )
            assert stale_export.status_code == 200
            assert stale_export.json()["blocked"] is True
            assert "TRAINING_PLAN_STALE" in {item["code"] for item in stale_export.json()["issues"]}
            with Session(engine) as session:
                samples = {item.relative_path: item for item in session.exec(select(Sample)).all()}
                assert samples["a.png"].split == samples["b.png"].split == "train"
                assert samples["c.png"].split == "val"
                assert samples["d.png"].split is None
                samples["c.png"].file_hash = ""
                session.add(samples["c.png"])
                session.commit()
            assert client.post(f"{base}/preview", json=request).json()["blocked"] is True
    finally:
        app.dependency_overrides.clear()


def test_confirmed_split_scope_exports_training_images_and_labels(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        Image.new("RGB", (16, 16), "white").save(tmp_path / "object.png")
        Image.new("RGB", (16, 16), "black").save(tmp_path / "pending.png")
        with TestClient(app) as client:
            dataset_id = client.post("/api/datasets", json={"name": "Training export", "root_path": str(tmp_path)}).json()["id"]
            assert client.post(f"/api/datasets/{dataset_id}/scan", json={"folder_path": str(tmp_path)}).status_code == 200
            items = client.get(f"/api/datasets/{dataset_id}/samples").json()["items"]
            object_id = next(item["id"] for item in items if item["filename"] == "object.png")
            assert client.put(f"/api/samples/{object_id}/annotations", json={
                "annotations": [{"label": "object", "shape_type": "rectangle", "points": [1, 1, 10, 10]}],
                "save_mode": "complete",
            }).status_code == 200
            base = f"/api/datasets/{dataset_id}"
            preview = client.post(f"{base}/training-split/preview", json={}).json()
            assert preview["candidate_count"] == 1
            committed = client.post(f"{base}/training-split/commit", json={"fingerprint": preview["fingerprint"]}).json()
            query = {"format": "yolo_detection", "include_images": True, "include_empty": True,
                     "completed_only": True, "sample_ids": committed["sample_ids"],
                     "expected_dataset_revision": committed["dataset_revision"]}
            exported = client.get(f"{base}/annotation-export", params=query)
            assert exported.status_code == 200
            assert "-training.zip" in exported.headers["content-disposition"]
            with ZipFile(BytesIO(exported.content)) as archive:
                names = set(archive.namelist())
                assert {"images/train/object.png", "labels/train/object.txt", "data.yaml"} <= names
                assert not any("pending" in name for name in names)
            stale = client.get(f"{base}/annotation-export", params={**query, "expected_dataset_revision": committed["dataset_revision"] - 1})
            assert stale.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_training_split_manual_exclusion_and_conflict(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            dataset_id = client.post("/api/datasets", json={"name": "Conflicts", "root_path": str(tmp_path)}).json()["id"]
            with Session(engine) as session:
                for name, split in [("a.png", "train"), ("b.png", "val"), ("c.png", None)]:
                    session.add(Sample(dataset_id=dataset_id, filename=name, relative_path=name,
                        absolute_path=str(tmp_path / name), file_type="image", extension=".png",
                        file_hash="other" if name == "c.png" else "same", annotation_progress="completed_empty", split=split))
                session.commit()
            base = f"/api/datasets/{dataset_id}/training-split"
            request = {"include_test": False}
            preview = client.post(f"{base}/preview", json=request).json()
            assert preview["blocked"] is True
            assert client.post(f"{base}/commit", json={**request, "fingerprint": preview["fingerprint"]}).status_code == 422
            first_id = preview["rows"][0]["sample_id"]
            fixed = client.post(f"{base}/preview", json={**request, "overrides": {str(first_id): "train"}}).json()
            assert fixed["blocked"] is False
            assert client.post(f"{base}/commit", json={**request, "overrides": {str(first_id): "val"}, "fingerprint": fixed["fingerprint"]}).status_code == 409
            assert client.post(f"{base}/commit", json={**request, "overrides": {str(first_id): "train"}, "fingerprint": fixed["fingerprint"]}).status_code == 200
            assert client.post(f"{base}/commit", json={**request, "overrides": {str(first_id): "train"}, "fingerprint": fixed["fingerprint"]}).status_code == 200
            excluded = client.post(f"{base}/preview", json={**request, "overrides": {str(first_id): None}}).json()
            assert excluded["blocked"] is False
            result = client.post(f"{base}/commit", json={**request, "overrides": {str(first_id): None}, "fingerprint": excluded["fingerprint"]})
            assert result.status_code == 200
            assert len(result.json()["sample_ids"]) == 1
            with Session(engine) as session:
                samples = {item.relative_path: item for item in session.exec(select(Sample)).all()}
                assert samples["a.png"].split == samples["b.png"].split == "train"
                assert samples["c.png"].split == "val"
            assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
    finally:
        app.dependency_overrides.clear()
