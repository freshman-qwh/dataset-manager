import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models.dataset import Dataset
from app.models.dataset_snapshot import DatasetSnapshot
from app.schemas.dataset_snapshot import DatasetSnapshotCreate
from app.services import dataset_snapshot_service
from app.services.dataset_revision_service import bump_dataset_revision


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def make_client(
    snapshot_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, object]:
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
    monkeypatch.setattr(
        dataset_snapshot_service,
        "_snapshot_root",
        lambda: snapshot_root.resolve(),
    )
    return TestClient(app), engine


def test_snapshot_api_freezes_metadata_and_has_deterministic_content_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "a.png").write_bytes(PNG_1X1)
    (raw_root / "b.png").write_bytes(PNG_1X1 + b"second")
    client, _engine = make_client(tmp_path / "snapshot-storage", monkeypatch)

    with client:
        created = client.post(
            "/api/datasets",
            json={"name": "Snapshots", "root_path": str(raw_root)},
        ).json()
        dataset_id = int(created["id"])
        assert client.post(
            f"/api/datasets/{dataset_id}/scan",
            json={"folder_path": str(raw_root)},
        ).status_code == 200
        samples = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"page_size": 10, "sort_by": "filename", "sort_order": "asc"},
        ).json()["items"]
        first_id = int(samples[0]["id"])
        assert client.patch(
            f"/api/samples/{first_id}",
            json={"tags": ["trainable"], "split": "train", "review_status": "approved"},
        ).status_code == 200
        assert client.put(
            f"/api/samples/{first_id}/annotations",
            json={
                "save_mode": "complete",
                "annotations": [
                    {
                        "label": "defect",
                        "shape_type": "rectangle",
                        "points": [0, 0, 1, 1],
                    }
                ],
            },
        ).status_code == 200
        revision = client.get(f"/api/datasets/{dataset_id}").json()["revision"]
        request = {
            "name": "approved train",
            "sample_query": {
                "review_status": "approved",
                "split": "train",
                "sort_by": "relative_path",
                "sort_order": "asc",
            },
            "export_config": {
                "format": "coco_detection",
                "include_empty": True,
                "class_map": [],
            },
        }

        first = client.post(f"/api/datasets/{dataset_id}/snapshots", json=request)
        second = client.post(f"/api/datasets/{dataset_id}/snapshots", json=request)
        assert first.status_code == second.status_code == 201
        first_data = first.json()
        second_data = second.json()
        assert first_data["dataset_revision"] == revision
        assert first_data["sample_count"] == 1
        assert first_data["annotation_count"] == 1
        assert first_data["class_count"] == 1
        assert first_data["content_sha256"] == second_data["content_sha256"]
        assert client.get(f"/api/datasets/{dataset_id}").json()["revision"] == revision

        listed = client.get(f"/api/datasets/{dataset_id}/snapshots")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [second_data["id"], first_data["id"]]

        detail = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{first_data['id']}"
        )
        content = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{first_data['id']}/content"
        )
        download = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{first_data['id']}/download"
        )
        assert detail.status_code == content.status_code == download.status_code == 200
        document = content.json()
        assert document["content_sha256"] == first_data["content_sha256"]
        assert document["content"]["samples"][0]["relative_path"] == "a.png"
        assert document["content"]["samples"][0]["file_hash"]
        assert document["content"]["samples"][0]["tags"] == ["trainable"]
        assert document["content"]["samples"][0]["split"] == "train"
        assert document["content"]["samples"][0]["annotations"][0]["label"] == "defect"
        assert {item["name"] for item in document["content"]["class_map"]} == {"defect"}
        assert download.headers["content-type"].startswith("application/json")
        assert "attachment" in download.headers["content-disposition"]

        assert client.patch(
            f"/api/samples/{first_id}", json={"notes": "changed after snapshot"}
        ).status_code == 200
        third = client.post(f"/api/datasets/{dataset_id}/snapshots", json=request)
        assert third.status_code == 201
        assert third.json()["dataset_revision"] == revision + 1
        assert third.json()["content_sha256"] != first_data["content_sha256"]
        frozen = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{first_data['id']}/content"
        ).json()
        assert frozen["content"]["samples"][0]["notes"] is None

        assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
        assert list((tmp_path / "snapshot-storage").rglob("*.json")) == []

    app.dependency_overrides.clear()


def test_snapshot_rejects_revision_change_during_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        dataset_snapshot_service,
        "_snapshot_root",
        lambda: (tmp_path / "snapshots").resolve(),
    )
    original_build = dataset_snapshot_service._build_snapshot_content

    with Session(engine) as session:
        dataset = Dataset(name="Concurrent snapshot")
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        dataset_id = dataset.id or 0

        def build_then_change(*args: object, **kwargs: object):
            content = original_build(*args, **kwargs)
            bump_dataset_revision(session, dataset_id)
            return content

        monkeypatch.setattr(dataset_snapshot_service, "_build_snapshot_content", build_then_change)
        with pytest.raises(dataset_snapshot_service.DatasetSnapshotStaleError):
            dataset_snapshot_service.create_snapshot(
                session,
                dataset_id,
                DatasetSnapshotCreate(),
            )
        assert session.exec(select(DatasetSnapshot)).all() == []
        assert not (tmp_path / "snapshots").exists()


def test_snapshot_integrity_failure_returns_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _engine = make_client(tmp_path / "snapshot-storage", monkeypatch)
    with client:
        dataset_id = client.post("/api/datasets", json={"name": "Integrity"}).json()["id"]
        snapshot = client.post(
            f"/api/datasets/{dataset_id}/snapshots",
            json={"name": "original"},
        ).json()
        artifact = next((tmp_path / "snapshot-storage").rglob("*.json"))
        document = json.loads(artifact.read_text(encoding="utf-8"))
        document["content"]["dataset"]["name"] = "tampered"
        artifact.write_text(json.dumps(document), encoding="utf-8")

        response = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{snapshot['id']}/content"
        )
        assert response.status_code == 410
        assert "integrity" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_snapshot_diff_and_training_label_rebuild_are_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "a.csv").write_text("value,label\n1,a\n", encoding="utf-8")
    (raw_root / "b.csv").write_text("value,label\n2,b\n", encoding="utf-8")
    client, _engine = make_client(tmp_path / "snapshot-storage", monkeypatch)

    with client:
        dataset_id = client.post(
            "/api/datasets",
            json={
                "name": "Snapshot diff",
                "root_path": str(raw_root),
                "task_type": "classification",
            },
        ).json()["id"]
        assert client.post(
            f"/api/datasets/{dataset_id}/scan",
            json={"folder_path": str(raw_root)},
        ).status_code == 200
        samples = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"page_size": 10, "sort_by": "filename", "sort_order": "asc"},
        ).json()["items"]
        a_id = samples[0]["id"]
        b_id = samples[1]["id"]
        assert client.patch(
            f"/api/samples/{a_id}", json={"tags": ["old"], "split": "train"}
        ).status_code == 200
        request = {
            "sample_query": {"sort_by": "relative_path", "sort_order": "asc"},
            "export_config": {"format": "csv", "include_empty": True, "class_map": []},
        }
        base = client.post(
            f"/api/datasets/{dataset_id}/snapshots", json={**request, "name": "base"}
        ).json()

        assert client.patch(
            f"/api/samples/{a_id}",
            json={
                "tags": ["new"],
                "split": "val",
                "review_status": "approved",
            },
        ).status_code == 200
        (raw_root / "c.csv").write_text("value,label\n3,c\n", encoding="utf-8")
        assert client.post(
            f"/api/datasets/{dataset_id}/scan",
            json={"folder_path": str(raw_root)},
        ).status_code == 200
        assert client.delete(f"/api/samples/{b_id}").status_code == 200
        target = client.post(
            f"/api/datasets/{dataset_id}/snapshots", json={**request, "name": "target"}
        ).json()

        diff = client.get(
            f"/api/datasets/{dataset_id}/snapshots/compare",
            params={
                "base_snapshot_id": base["id"],
                "target_snapshot_id": target["id"],
            },
        )
        assert diff.status_code == 200
        result = diff.json()
        assert result["summary"] == {
            "added": 1,
            "removed": 1,
            "file_changed": 0,
            "metadata_changed": 1,
            "tags_changed": 1,
            "split_changed": 1,
            "annotations_changed": 0,
            "changed_samples": 3,
        }
        assert result["total"] == 3
        filtered = client.get(
            f"/api/datasets/{dataset_id}/snapshots/compare",
            params={
                "base_snapshot_id": base["id"],
                "target_snapshot_id": target["id"],
                "change_type": "tags",
                "page_size": 1,
            },
        ).json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["sample_id"] == a_id
        assert set(filtered["items"][0]["change_types"]) == {"metadata", "tags", "split"}

        revision = client.get(f"/api/datasets/{dataset_id}").json()["revision"]
        first_labels = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{target['id']}/training-labels"
        )
        second_labels = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{target['id']}/training-labels"
        )
        download_one = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{target['id']}/training-labels/download"
        )
        download_two = client.get(
            f"/api/datasets/{dataset_id}/snapshots/{target['id']}/training-labels/download"
        )
        assert first_labels.status_code == second_labels.status_code == 200
        assert first_labels.json()["label_sha256"] == second_labels.json()["label_sha256"]
        assert first_labels.json()["sample_count"] == 2
        assert first_labels.json()["format"] == "csv"
        labels_by_path = {
            item["relative_path"]: item["labels"] for item in first_labels.json()["labels"]
        }
        assert labels_by_path == {"a.csv": ["new"], "c.csv": []}
        assert download_one.content == download_two.content
        assert "attachment" in download_one.headers["content-disposition"]
        assert client.get(f"/api/datasets/{dataset_id}").json()["revision"] == revision

    app.dependency_overrides.clear()
