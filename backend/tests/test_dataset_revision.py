import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.models.dataset import Dataset
from app.services.dataset_revision_service import DatasetRevisionTracker


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


def dataset_revision(client: TestClient, dataset_id: int) -> int:
    response = client.get(f"/api/datasets/{dataset_id}")
    assert response.status_code == 200
    return int(response.json()["revision"])


def test_revision_covers_core_metadata_writes_once(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "a.png").write_bytes(PNG_1X1)
    (raw_root / "b.png").write_bytes(PNG_1X1)

    with make_client() as client:
        created = client.post(
            "/api/datasets",
            json={"name": "Revision", "root_path": str(raw_root)},
        )
        assert created.status_code == 201
        dataset_id = int(created.json()["id"])
        assert created.json()["revision"] == 1

        scan = client.post(
            f"/api/datasets/{dataset_id}/scan",
            json={"folder_path": str(raw_root)},
        )
        assert scan.status_code == 200
        assert scan.json()["imported"] == 2
        assert dataset_revision(client, dataset_id) == 2

        unchanged_scan = client.post(
            f"/api/datasets/{dataset_id}/scan",
            json={"folder_path": str(raw_root)},
        )
        assert unchanged_scan.status_code == 200
        assert unchanged_scan.json()["unchanged"] == 2
        assert dataset_revision(client, dataset_id) == 2

        samples = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"page_size": 10, "sort_by": "filename"},
        ).json()["items"]
        first_id = int(samples[0]["id"])
        sample_ids = [int(item["id"]) for item in samples]

        assert client.patch(f"/api/samples/{first_id}", json={"notes": "checked"}).status_code == 200
        assert dataset_revision(client, dataset_id) == 3

        batch = client.patch(
            f"/api/datasets/{dataset_id}/samples/batch",
            json={"sample_ids": sample_ids, "review_status": "in_review"},
        )
        assert batch.status_code == 200
        assert batch.json()["updated"] == 2
        assert dataset_revision(client, dataset_id) == 4

        tag = client.post(
            f"/api/datasets/{dataset_id}/tags",
            json={"name": "reviewed"},
        )
        assert tag.status_code == 201
        assert dataset_revision(client, dataset_id) == 5

        split = client.post(
            f"/api/datasets/{dataset_id}/split-plan",
            json={
                "train_ratio": 1,
                "val_ratio": 1,
                "test_ratio": 0,
                "include_test": False,
                "stratify_by_tags": False,
                "normal_only": True,
                "only_unassigned": False,
                "seed": 7,
            },
        )
        assert split.status_code == 200
        assert dataset_revision(client, dataset_id) == 6

        annotations = client.put(
            f"/api/samples/{first_id}/annotations",
            json={
                "save_mode": "draft",
                "annotations": [
                    {
                        "label": "defect",
                        "shape_type": "rectangle",
                        "points": [0, 0, 1, 1],
                    }
                ],
            },
        )
        assert annotations.status_code == 200
        assert dataset_revision(client, dataset_id) == 7

        sync_tags = client.post(f"/api/samples/{first_id}/annotations/sync-sample-tags")
        assert sync_tags.status_code == 200
        assert sync_tags.json()["added_tags"] == ["defect"]
        assert dataset_revision(client, dataset_id) == 8

        second_sync = client.post(f"/api/samples/{first_id}/annotations/sync-sample-tags")
        assert second_sync.status_code == 200
        assert second_sync.json()["added_tags"] == []
        assert dataset_revision(client, dataset_id) == 8

        metadata_path = tmp_path / "metadata.csv"
        metadata_path.write_text("relative_path,notes\na.png,from import\nb.png,from import\n", encoding="utf-8")
        preview = client.post(
            f"/api/datasets/{dataset_id}/import-metadata",
            json={"file_path": str(metadata_path), "match_by": "relative_path", "dry_run": True},
        )
        assert preview.status_code == 200
        assert dataset_revision(client, dataset_id) == 8

        imported = client.post(
            f"/api/datasets/{dataset_id}/import-metadata",
            json={
                "file_path": str(metadata_path),
                "match_by": "relative_path",
                "dry_run": False,
                "expected_source_sha256": preview.json()["source_sha256"],
            },
        )
        assert imported.status_code == 200
        assert imported.json()["updated"] == 2
        assert dataset_revision(client, dataset_id) == 9

        updated = client.patch(f"/api/datasets/{dataset_id}", json={"description": "v2"})
        assert updated.status_code == 200
        assert updated.json()["revision"] == 10

    app.dependency_overrides.clear()


def test_labelme_directory_import_advances_revision_once_for_multiple_samples(tmp_path: Path) -> None:
    raw_root = tmp_path / "images"
    import_root = tmp_path / "labelme"
    raw_root.mkdir()
    import_root.mkdir()
    for filename in ("a.png", "b.png"):
        (raw_root / filename).write_bytes(PNG_1X1)
        (import_root / filename.replace(".png", ".json")).write_text(
            json.dumps(
                {
                    "version": "5.0.0",
                    "flags": {},
                    "shapes": [
                        {
                            "label": "object",
                            "shape_type": "rectangle",
                            "points": [[0, 0], [1, 1]],
                        }
                    ],
                    "imagePath": filename,
                    "imageData": None,
                    "imageWidth": 1,
                    "imageHeight": 1,
                }
            ),
            encoding="utf-8",
        )

    with make_client() as client:
        dataset = client.post(
            "/api/datasets",
            json={"name": "LabelMe revision", "root_path": str(raw_root)},
        ).json()
        dataset_id = int(dataset["id"])
        assert client.post(
            f"/api/datasets/{dataset_id}/scan",
            json={"folder_path": str(raw_root)},
        ).status_code == 200
        before = dataset_revision(client, dataset_id)

        preview = client.post(
            f"/api/datasets/{dataset_id}/annotations/import-labelme",
            json={"path": str(import_root), "mode": "directory", "dry_run": True},
        )
        assert preview.status_code == 200
        imported = client.post(
            f"/api/datasets/{dataset_id}/annotations/import-labelme",
            json={
                "path": str(import_root),
                "mode": "directory",
                "dry_run": False,
                "expected_source_sha256": preview.json()["source_sha256"],
                "expected_plan_fingerprint": preview.json()["plan_fingerprint"],
            },
        )
        assert imported.status_code == 200
        assert imported.json()["imported_samples"] == 2
        assert dataset_revision(client, dataset_id) == before + 1

    app.dependency_overrides.clear()


def test_revision_tracker_advances_only_once_across_commits(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Tracked")
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        assert dataset.id is not None
        dataset_id = dataset.id
        tracker = DatasetRevisionTracker(dataset_id)

        assert tracker.bump_once(session) == 2
        session.commit()
        assert tracker.bump_once(session) == 2
        session.commit()

    with Session(engine) as session:
        stored = session.get(Dataset, dataset_id)
        assert stored is not None
        assert stored.revision == 2
    engine.dispose()
