from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app


def make_client():
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


def test_dataset_scan_batch_and_export(tmp_path: Path):
    data_root = tmp_path / "dataset"
    data_root.mkdir()
    sample_file = data_root / "measurements.csv"
    sample_file.write_text("id,value\n1,42\n", encoding="utf-8")
    second_file = data_root / "zeta.csv"
    second_file.write_text("id,value\n2,99\n", encoding="utf-8")

    with make_client() as client:
        created = client.post(
            "/api/datasets",
            json={
                "name": "Lab Run",
                "task_type": "tabular",
                "root_path": str(data_root),
                "source": "instrument-a",
                "modality": "csv",
                "license": "internal",
                "owner": "research-team",
                "project": "quality-study",
                "notes": "baseline dataset",
            },
        )
        assert created.status_code == 201
        dataset = created.json()

        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        scan_result = scan.json()
        assert scan_result["imported"] == 2
        assert scan_result["updated"] == 0
        assert scan_result["missing"] == 0

        samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"sort_by": "filename", "sort_order": "asc", "page_size": 1},
        )
        assert samples.status_code == 200
        samples_payload = samples.json()
        assert samples_payload["total"] == 2
        assert samples_payload["page"] == 1
        assert len(samples_payload["items"]) == 1
        assert samples_payload["items"][0]["filename"] == "measurements.csv"
        sample_id = samples_payload["items"][0]["id"]

        batch = client.patch(
            f"/api/datasets/{dataset['id']}/samples/batch",
            json={"sample_ids": [sample_id], "split": "train", "add_tags": ["accepted"]},
        )
        assert batch.status_code == 200
        assert batch.json()["updated"] == 1

        preview = client.get(f"/api/samples/{sample_id}/preview")
        assert preview.status_code == 200
        assert preview.json()["columns"] == ["id", "value"]
        assert preview.json()["rows"][0]["value"] == "42"

        exported = client.get(f"/api/datasets/{dataset['id']}/export-manifest", params={"tag": "accepted"})
        assert exported.status_code == 200
        manifest = exported.json()
        assert manifest["dataset"]["source"] == "instrument-a"
        assert manifest["filters"]["tag"] == "accepted"
        assert manifest["exported_sample_count"] == 1
        assert manifest["samples"][0]["split"] == "train"
        assert manifest["samples"][0]["tags"] == ["accepted"]

    app.dependency_overrides.clear()


def test_incremental_scan_reports_changed_and_missing(tmp_path: Path):
    data_root = tmp_path / "images"
    data_root.mkdir()
    image_file = data_root / "sample.png"
    image_file.write_bytes(b"first")

    with make_client() as client:
        dataset = client.post(
            "/api/datasets",
            json={"name": "Images", "root_path": str(data_root)},
        ).json()

        first_scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert first_scan.json()["imported"] == 1

        image_file.write_bytes(b"second")
        second_scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert second_scan.json()["updated"] == 1
        assert second_scan.json()["unchanged"] == 0

        image_file.unlink()
        third_scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert third_scan.json()["missing"] == 1

        samples = client.get(f"/api/datasets/{dataset['id']}/samples").json()
        assert samples["items"][0]["file_status"] == "missing"

    app.dependency_overrides.clear()


def test_dataset_update_delete_and_safe_scan_root(tmp_path: Path):
    drive_root = Path(tmp_path.anchor)

    with make_client() as client:
        created = client.post(
            "/api/datasets",
            json={"name": "Editable", "root_path": str(drive_root)},
        )
        assert created.status_code == 201
        dataset_id = created.json()["id"]

        updated = client.patch(
            f"/api/datasets/{dataset_id}",
            json={"owner": "curator", "project": "reviewed"},
        )
        assert updated.status_code == 200
        assert updated.json()["owner"] == "curator"

        rejected_scan = client.post(f"/api/datasets/{dataset_id}/scan", json={"folder_path": str(drive_root)})
        assert rejected_scan.status_code == 400

        deleted = client.delete(f"/api/datasets/{dataset_id}")
        assert deleted.status_code == 204
        missing = client.get(f"/api/datasets/{dataset_id}")
        assert missing.status_code == 404

    app.dependency_overrides.clear()


def test_filesystem_directory_browser(tmp_path: Path):
    child = tmp_path / "child"
    child.mkdir()

    with make_client() as client:
        listed = client.get("/api/filesystem/directories", params={"path": str(tmp_path)})
        assert listed.status_code == 200
        payload = listed.json()
        assert payload["current_path"] == str(tmp_path.resolve())
        assert any(entry["name"] == "child" for entry in payload["entries"])

    app.dependency_overrides.clear()


def test_v03_duplicates_tags_metadata_import_and_templates(tmp_path: Path):
    data_root = tmp_path / "v03"
    data_root.mkdir()
    first = data_root / "a.png"
    second = data_root / "b.png"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "relative_path,tags,split,notes,quality\n"
        "a.png,cat;review,train,good sample,high\n"
        "b.png,cat,val,duplicate sample,medium\n",
        encoding="utf-8",
    )
    metadata_json = tmp_path / "metadata.json"
    metadata_json.write_text(
        '[{"relative_path":"a.png","tags":["feline","checked"],"split":"test","quality":"verified"}]',
        encoding="utf-8",
    )
    absolute_metadata = tmp_path / "absolute_metadata.csv"
    absolute_metadata.write_text(
        f'absolute_path,tags,split\n"{first.resolve().as_posix()}",absolute,train\n',
        encoding="utf-8",
    )

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "V03", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        assert scan.json()["imported"] == 2

        created_tag = client.post(
            f"/api/datasets/{dataset['id']}/tags",
            json={
                "name": "cat",
                "color": "#ff0000",
                "description": "animal",
                "aliases": ["feline"],
            },
        )
        assert created_tag.status_code == 201
        tag_id = created_tag.json()["id"]

        updated_tag = client.patch(
            f"/api/tags/{tag_id}",
            json={"parent_id": None, "aliases": ["cat-a", "cat-b"]},
        )
        assert updated_tag.status_code == 200
        assert updated_tag.json()["aliases"] == ["cat-a", "cat-b"]

        conflicting_tag = client.post(
            f"/api/datasets/{dataset['id']}/tags",
            json={"name": "dog", "aliases": ["cat-a"]},
        )
        assert conflicting_tag.status_code == 409

        imported = client.post(
            f"/api/datasets/{dataset['id']}/import-metadata",
            json={
                "file_path": str(metadata),
                "match_by": "relative_path",
                "tag_column": "tags",
                "replace_tags": False,
            },
        )
        assert imported.status_code == 200
        assert imported.json()["updated"] == 2

        duplicates = client.get(f"/api/datasets/{dataset['id']}/duplicates")
        assert duplicates.status_code == 200
        assert duplicates.json()["group_count"] == 1
        assert duplicates.json()["duplicate_sample_count"] == 2

        stats = client.get(f"/api/stats/datasets/{dataset['id']}")
        assert stats.status_code == 200
        assert stats.json()["by_split"]["train"] == 1
        assert stats.json()["by_split"]["val"] == 1
        assert stats.json()["duplicate_groups"] == 1

        samples = client.get(f"/api/datasets/{dataset['id']}/samples", params={"search": "a.png"}).json()
        sample = samples["items"][0]
        assert sample["metadata"]["quality"] == "high"
        assert sample["split"] == "train"
        assert "cat" in [tag["name"] for tag in sample["tags"]]

        split_filtered = client.get(f"/api/datasets/{dataset['id']}/samples", params={"split": "train"}).json()
        assert split_filtered["total"] == 1
        assert split_filtered["items"][0]["relative_path"] == "a.png"

        json_imported = client.post(
            f"/api/datasets/{dataset['id']}/import-metadata",
            json={
                "file_path": str(metadata_json),
                "match_by": "relative_path",
                "tag_column": "tags",
                "replace_tags": False,
            },
        )
        assert json_imported.status_code == 200
        assert json_imported.json()["updated"] == 1
        updated_sample = client.get(f"/api/datasets/{dataset['id']}/samples", params={"search": "a.png"}).json()["items"][0]
        assert updated_sample["split"] == "test"
        assert updated_sample["metadata"]["quality"] == "verified"
        assert "cat" in [tag["name"] for tag in updated_sample["tags"]]
        assert "checked" in [tag["name"] for tag in updated_sample["tags"]]

        absolute_imported = client.post(
            f"/api/datasets/{dataset['id']}/import-metadata",
            json={
                "file_path": str(absolute_metadata),
                "match_by": "absolute_path",
                "tag_column": "tags",
                "replace_tags": False,
            },
        )
        assert absolute_imported.status_code == 200
        assert absolute_imported.json()["updated"] == 1
        absolute_sample = client.get(f"/api/datasets/{dataset['id']}/samples", params={"tag": "absolute"}).json()
        assert absolute_sample["total"] == 1

        csv_template = client.get(f"/api/datasets/{dataset['id']}/export-template", params={"format": "csv"})
        assert csv_template.status_code == 200
        assert csv_template.json()["payload"]["columns"][0] == "relative_path"

        coco_template = client.get(f"/api/datasets/{dataset['id']}/export-template", params={"format": "coco"})
        assert coco_template.status_code == 200
        assert len(coco_template.json()["payload"]["images"]) == 2

        yolo_template = client.get(f"/api/datasets/{dataset['id']}/export-template", params={"format": "yolo"})
        assert yolo_template.status_code == 200
        assert "cat" in yolo_template.json()["payload"]["classes"]

    app.dependency_overrides.clear()
