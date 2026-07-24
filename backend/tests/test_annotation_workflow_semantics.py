import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def make_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def create_sample(client: TestClient, tmp_path: Path, name: str) -> tuple[int, int]:
    data_root = tmp_path / name
    data_root.mkdir()
    (data_root / "sample.png").write_bytes(PNG_1X1)
    dataset = client.post("/api/datasets", json={"name": name, "root_path": str(data_root)}).json()
    assert client.post(
        f"/api/datasets/{dataset['id']}/scan",
        json={"folder_path": str(data_root)},
    ).status_code == 200
    sample = client.get(f"/api/datasets/{dataset['id']}/samples").json()["items"][0]
    return dataset["id"], sample["id"]


def test_confirm_empty_is_completed_without_quality_or_precheck_missing_issue(tmp_path: Path):
    with make_client() as client:
        dataset_id, sample_id = create_sample(client, tmp_path, "confirmed-negative")

        confirmed = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [], "save_mode": "confirm_empty"},
        )
        assert confirmed.status_code == 200
        assert confirmed.json() == []

        sample = client.get(f"/api/samples/{sample_id}").json()
        assert sample["annotation_progress"] == "completed_empty"
        assert sample["review_status"] == "in_review"

        quality = client.get(f"/api/datasets/{dataset_id}/quality-report").json()
        assert quality["confirmed_empty_sample_count"] == 1
        sample_issue_codes = {
            issue["code"] for issue in quality["issues"] if issue["sample_id"] == sample_id
        }
        assert "ANNOTATION_NOT_STARTED" not in sample_issue_codes
        assert "ANNOTATION_INCOMPLETE" not in sample_issue_codes
        assert "ANNOTATION_PROGRESS_CONFLICT" not in sample_issue_codes

        precheck = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-precheck",
            json={"format": "yolo_detection"},
        ).json()
        issue_codes = {issue["code"] for issue in precheck["issues"]}
        assert "CONFIRMED_EMPTY_SAMPLE_SKIPPED" in issue_codes
        assert "UNFINISHED_SAMPLE_SKIPPED" not in issue_codes

    app.dependency_overrides.clear()


def test_completion_modes_reject_contradictory_payload_without_erasing_objects(tmp_path: Path):
    with make_client() as client:
        _, sample_id = create_sample(client, tmp_path, "completion-guards")
        annotation = {"label": "defect", "shape_type": "rectangle", "points": [0, 0, 1, 1]}
        assert client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [annotation], "save_mode": "draft"},
        ).status_code == 200

        invalid_empty = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [annotation], "save_mode": "confirm_empty"},
        )
        assert invalid_empty.status_code == 400
        invalid_complete = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [], "save_mode": "complete"},
        )
        assert invalid_complete.status_code == 400

        current = client.get(f"/api/samples/{sample_id}/annotations").json()
        assert [item["label"] for item in current] == ["defect"]
        assert client.get(f"/api/samples/{sample_id}").json()["annotation_progress"] == "in_progress"

    app.dependency_overrides.clear()


def test_annotation_classes_do_not_modify_tags_until_explicit_additive_sync(tmp_path: Path):
    with make_client() as client:
        dataset_id, sample_id = create_sample(client, tmp_path, "class-tag-boundary")
        assert client.patch(f"/api/samples/{sample_id}", json={"tags": ["keep-me"]}).status_code == 200

        saved = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={
                "annotations": [
                    {"label": "defect", "shape_type": "rectangle", "points": [0, 0, 1, 1]}
                ],
                "save_mode": "complete",
            },
        )
        assert saved.status_code == 200
        annotation = saved.json()[0]
        assert annotation["class_id"] is not None
        assert {tag["name"] for tag in client.get(f"/api/samples/{sample_id}").json()["tags"]} == {"keep-me"}

        synced = client.post(f"/api/samples/{sample_id}/annotations/sync-sample-tags")
        assert synced.status_code == 200
        assert synced.json()["added_tags"] == ["defect"]
        assert {tag["name"] for tag in client.get(f"/api/samples/{sample_id}").json()["tags"]} == {
            "keep-me",
            "defect",
        }

        repeated = client.post(f"/api/samples/{sample_id}/annotations/sync-sample-tags").json()
        assert repeated["added_tags"] == []
        assert repeated["existing_tags"] == ["defect"]

        annotation_class = client.get(f"/api/datasets/{dataset_id}/annotation-classes").json()[0]
        renamed = client.patch(
            f"/api/annotation-classes/{annotation_class['id']}",
            json={"name": "surface-defect"},
        )
        assert renamed.status_code == 200
        current = client.get(f"/api/samples/{sample_id}/annotations").json()[0]
        assert current["label"] == "surface-defect"
        assert current["class_id"] == annotation_class["id"]

        assert client.delete(f"/api/annotation-classes/{annotation_class['id']}").status_code == 204
        detached = client.get(f"/api/samples/{sample_id}/annotations").json()[0]
        assert detached["label"] == "surface-defect"
        assert detached["class_id"] is None

    app.dependency_overrides.clear()
