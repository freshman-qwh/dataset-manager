from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models.dataset_saved_view import DatasetSavedView


def make_client() -> tuple[TestClient, object]:
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
    return TestClient(app), engine


def test_saved_view_api_create_list_restore_and_delete_without_revision_change() -> None:
    client, engine = make_client()
    with client:
        dataset = client.post(
            "/api/datasets",
            json={"name": "Reusable queues", "task_type": "detection"},
        ).json()
        dataset_id = int(dataset["id"])
        revision = int(dataset["revision"])
        payload = {
            "name": "  待审核训练集  ",
            "queue_scope": "current_split",
            "sample_query": {
                "search": "  cat  ",
                "file_type": "image",
                "file_status": "normal",
                "tag": "  animal  ",
                "split": " train ",
                "review_status": "in_review",
                "annotation_progress": "completed_with_objects",
                "sort_by": "filename",
                "sort_order": "asc",
            },
        }

        created_response = client.post(
            f"/api/datasets/{dataset_id}/saved-views", json=payload
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["name"] == "待审核训练集"
        assert created["task_type"] == "detection"
        assert created["queue_scope"] == "current_split"
        assert created["sample_query"] == {
            "search": "cat",
            "file_type": "image",
            "file_status": "normal",
            "tag": "animal",
            "split": "train",
            "review_status": "in_review",
            "annotation_progress": "completed_with_objects",
            "sort_by": "filename",
            "sort_order": "asc",
        }
        assert client.get(f"/api/datasets/{dataset_id}").json()["revision"] == revision

        listed = client.get(f"/api/datasets/{dataset_id}/saved-views")
        detail = client.get(
            f"/api/datasets/{dataset_id}/saved-views/{created['id']}"
        )
        assert listed.status_code == detail.status_code == 200
        assert listed.json() == [created]
        assert detail.json() == created

        duplicate = client.post(
            f"/api/datasets/{dataset_id}/saved-views",
            json={**payload, "name": "待审核训练集".upper()},
        )
        assert duplicate.status_code == 409

        assert client.patch(
            f"/api/datasets/{dataset_id}", json={"task_type": "segmentation"}
        ).status_code == 200
        frozen = client.get(
            f"/api/datasets/{dataset_id}/saved-views/{created['id']}"
        ).json()
        assert frozen["task_type"] == "detection"
        revision_after_dataset_update = client.get(
            f"/api/datasets/{dataset_id}"
        ).json()["revision"]

        deleted = client.delete(
            f"/api/datasets/{dataset_id}/saved-views/{created['id']}"
        )
        assert deleted.status_code == 204
        assert client.get(
            f"/api/datasets/{dataset_id}/saved-views/{created['id']}"
        ).status_code == 404
        assert client.get(f"/api/datasets/{dataset_id}").json()["revision"] == revision_after_dataset_update

    with Session(engine) as session:
        assert session.exec(select(DatasetSavedView)).all() == []
    app.dependency_overrides.clear()


def test_saved_view_validation_and_dataset_cleanup() -> None:
    client, engine = make_client()
    with client:
        first = client.post("/api/datasets", json={"name": "First"}).json()
        second = client.post("/api/datasets", json={"name": "Second"}).json()
        invalid_split = client.post(
            f"/api/datasets/{first['id']}/saved-views",
            json={
                "name": "No split",
                "queue_scope": "current_split",
                "sample_query": {"sort_by": "filename"},
            },
        )
        invalid_sort = client.post(
            f"/api/datasets/{first['id']}/saved-views",
            json={"name": "Bad sort", "sample_query": {"sort_by": "unknown"}},
        )
        assert invalid_split.status_code == invalid_sort.status_code == 422

        created = client.post(
            f"/api/datasets/{first['id']}/saved-views",
            json={"name": "First view", "sample_query": {"sort_by": "filename"}},
        ).json()
        assert client.get(
            f"/api/datasets/{second['id']}/saved-views/{created['id']}"
        ).status_code == 404
        assert client.delete(f"/api/datasets/{first['id']}").status_code == 204

    with Session(engine) as session:
        assert session.exec(select(DatasetSavedView)).all() == []
    app.dependency_overrides.clear()
