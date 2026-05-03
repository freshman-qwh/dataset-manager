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


def create_labeled_dataset(client: TestClient, tmp_path: Path, name: str, labels: dict[str, str]) -> int:
    data_root = tmp_path / name
    data_root.mkdir()
    rows = ["relative_path,tags\n"]
    for filename, tags in labels.items():
        (data_root / filename).write_bytes(filename.encode("utf-8"))
        rows.append(f"{filename},{tags}\n")
    metadata = tmp_path / f"{name}_metadata.csv"
    metadata.write_text("".join(rows), encoding="utf-8")

    dataset = client.post("/api/datasets", json={"name": name, "root_path": str(data_root)}).json()
    scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
    assert scan.status_code == 200
    assert scan.json()["imported"] == len(labels)

    imported = client.post(
        f"/api/datasets/{dataset['id']}/import-metadata",
        json={"file_path": str(metadata), "match_by": "relative_path", "tag_column": "tags"},
    )
    assert imported.status_code == 200
    assert imported.json()["updated"] == len(labels)
    return dataset["id"]


def split_dataset(client: TestClient, dataset_id: int, **overrides):
    payload = {
        "train_ratio": 70,
        "val_ratio": 30,
        "test_ratio": 0,
        "include_test": False,
        "stratify_by_tags": True,
        "normal_only": True,
        "only_unassigned": False,
        "seed": 42,
    }
    payload.update(overrides)
    split = client.post(f"/api/datasets/{dataset_id}/split-plan", json=payload)
    assert split.status_code == 200
    return split.json()


def sample_splits_for_tag(client: TestClient, dataset_id: int, tag_name: str) -> set[str]:
    samples = client.get(
        f"/api/datasets/{dataset_id}/samples",
        params={"tag": tag_name, "page_size": 200},
    ).json()["items"]
    return {sample["split"] for sample in samples}


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
        assert created.json()["auto_scan_on_open"] is False

        updated = client.patch(
            f"/api/datasets/{dataset_id}",
            json={"owner": "curator", "project": "reviewed", "auto_scan_on_open": True},
        )
        assert updated.status_code == 200
        assert updated.json()["owner"] == "curator"
        assert updated.json()["auto_scan_on_open"] is True

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
        duplicate_filtered = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"file_status": "duplicate"},
        )
        assert duplicate_filtered.status_code == 200
        assert duplicate_filtered.json()["total"] == 2

        stats = client.get(f"/api/stats/datasets/{dataset['id']}")
        assert stats.status_code == 200
        assert stats.json()["by_split"]["train"] == 1
        assert stats.json()["by_split"]["val"] == 1
        assert stats.json()["duplicate_groups"] == 1
        assert stats.json()["unlabeled_samples"] == 0

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


def test_v03_review_missing_repair_and_metadata_delete(tmp_path: Path):
    data_root = tmp_path / "review"
    data_root.mkdir()
    first = data_root / "first.png"
    second = data_root / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    remount_root = tmp_path / "remount"
    remount_root.mkdir()
    repaired_first = remount_root / "first.png"
    repaired_first.write_bytes(b"first repaired")

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Review", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        assert scan.json()["imported"] == 2

        samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"sort_by": "filename", "sort_order": "asc"},
        ).json()["items"]
        first_id = samples[0]["id"]
        second_id = samples[1]["id"]
        assert samples[0]["review_status"] == "unlabeled"

        updated = client.patch(f"/api/samples/{first_id}", json={"review_status": "approved"})
        assert updated.status_code == 200
        assert updated.json()["review_status"] == "approved"

        batch = client.patch(
            f"/api/datasets/{dataset['id']}/samples/batch",
            json={"sample_ids": [second_id], "review_status": "in_review"},
        )
        assert batch.status_code == 200
        review_filtered = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"review_status": "in_review"},
        ).json()
        assert review_filtered["total"] == 1
        assert review_filtered["items"][0]["id"] == second_id

        stats = client.get(f"/api/stats/datasets/{dataset['id']}").json()
        assert stats["by_review_status"]["approved"] == 1
        assert stats["by_review_status"]["in_review"] == 1
        assert stats["unlabeled_samples"] == 2

        first.unlink()
        missing_scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert missing_scan.status_code == 200
        assert missing_scan.json()["missing"] == 1

        missing_samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"file_status": "missing"},
        ).json()
        assert missing_samples["total"] == 1
        assert missing_samples["items"][0]["id"] == first_id

        repaired = client.patch(f"/api/samples/{first_id}/repair", json={"file_path": str(repaired_first)})
        assert repaired.status_code == 200
        assert repaired.json()["file_status"] == "normal"
        assert repaired.json()["absolute_path"] == str(repaired_first.resolve())

        second.unlink()
        missing_scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert missing_scan.status_code == 200
        assert missing_scan.json()["missing"] >= 1
        repaired_second = remount_root / "second.png"
        repaired_second.write_bytes(b"second repaired")
        repair_result = client.post(
            f"/api/datasets/{dataset['id']}/repair-missing",
            json={"root_path": str(remount_root), "update_dataset_root": True},
        )
        assert repair_result.status_code == 200
        assert repair_result.json()["repaired"] >= 1
        assert client.get(f"/api/datasets/{dataset['id']}").json()["root_path"] == str(remount_root.resolve())

        single_delete = client.delete(f"/api/samples/{first_id}")
        assert single_delete.status_code == 200
        assert single_delete.json()["deleted"] == 1
        assert repaired_first.exists()

        batch_delete = client.post(
            f"/api/datasets/{dataset['id']}/samples/delete",
            json={"sample_ids": [second_id, 999999]},
        )
        assert batch_delete.status_code == 200
        assert batch_delete.json()["deleted"] == 1
        assert batch_delete.json()["skipped"] == 1
        assert repaired_second.exists()
        assert client.get(f"/api/datasets/{dataset['id']}/samples").json()["total"] == 0

    app.dependency_overrides.clear()


def test_v03_stratified_split_plan(tmp_path: Path):
    data_root = tmp_path / "split"
    data_root.mkdir()
    rows = ["relative_path,tags\n"]
    for index in range(8):
        path = data_root / f"sample_{index}.png"
        path.write_bytes(f"sample-{index}".encode("utf-8"))
        label = "rare" if index < 3 else "common"
        rows.append(f"{path.name},{label}\n")
    metadata = tmp_path / "split_metadata.csv"
    metadata.write_text("".join(rows), encoding="utf-8")

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Split", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        assert scan.json()["imported"] == 8

        imported = client.post(
            f"/api/datasets/{dataset['id']}/import-metadata",
            json={"file_path": str(metadata), "match_by": "relative_path", "tag_column": "tags"},
        )
        assert imported.status_code == 200
        assert imported.json()["updated"] == 8

        split = client.post(
            f"/api/datasets/{dataset['id']}/split-plan",
            json={
                "train_ratio": 50,
                "val_ratio": 25,
                "test_ratio": 25,
                "include_test": True,
                "stratify_by_tags": True,
                "normal_only": True,
                "only_unassigned": False,
                "seed": 7,
            },
        )
        assert split.status_code == 200
        payload = split.json()
        assert payload["updated"] == 8
        assert payload["train"] + payload["val"] + payload["test"] == 8
        assert payload["val"] > 0
        assert payload["test"] > 0

        stats = client.get(f"/api/stats/datasets/{dataset['id']}").json()
        assert stats["by_split"]["train"] == payload["train"]
        assert stats["by_split"]["val"] == payload["val"]
        assert stats["by_split"]["test"] == payload["test"]

    app.dependency_overrides.clear()


def test_v03_multilabel_split_warning_uses_real_tag_counts(tmp_path: Path):
    data_root = tmp_path / "multilabel"
    data_root.mkdir()
    rows = ["relative_path,tags\n"]
    labels = {
        "a.png": "ok",
        "b.png": "ok;ng",
        "c.png": "ng",
        "d.png": "",
    }
    for name, tags in labels.items():
        (data_root / name).write_bytes(name.encode("utf-8"))
        rows.append(f"{name},{tags}\n")
    metadata = tmp_path / "multilabel_metadata.csv"
    metadata.write_text("".join(rows), encoding="utf-8")

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Multilabel", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        assert scan.json()["imported"] == 4

        imported = client.post(
            f"/api/datasets/{dataset['id']}/import-metadata",
            json={"file_path": str(metadata), "match_by": "relative_path", "tag_column": "tags"},
        )
        assert imported.status_code == 200
        assert imported.json()["updated"] == 4

        split = client.post(
            f"/api/datasets/{dataset['id']}/split-plan",
            json={
                "train_ratio": 50,
                "val_ratio": 50,
                "test_ratio": 0,
                "include_test": False,
                "stratify_by_tags": True,
                "normal_only": True,
                "only_unassigned": False,
                "seed": 42,
            },
        )
        assert split.status_code == 200
        warnings = split.json()["warnings"]
        assert not any(item.startswith("ok: only 1") for item in warnings)
        assert not any(item.startswith("ng: only 1") for item in warnings)

        ok_samples = client.get(f"/api/datasets/{dataset['id']}/samples", params={"tag": "ok"}).json()["items"]
        assert {sample["split"] for sample in ok_samples} >= {"val"}

    app.dependency_overrides.clear()


def test_v03_stratified_split_uses_multilabel_samples_for_validation_floor(tmp_path: Path):
    data_root = tmp_path / "small_multilabel"
    data_root.mkdir()
    labels = {
        "untagged_0.png": "",
        "untagged_1.png": "",
        "untagged_2.png": "",
        "untagged_3.png": "",
        "untagged_4.png": "",
        "untagged_5.png": "",
        "untagged_6.png": "",
        "ng_0.png": "ng",
        "ng_1.png": "ng",
        "ng_2.png": "ng",
        "father_0.png": "father",
        "father_1.png": "father",
        "father_ok_0.png": "father;ok",
        "father_ok_1.png": "father;ok",
        "ok_0.png": "ok",
    }
    rows = ["relative_path,tags\n"]
    for name, tags in labels.items():
        (data_root / name).write_bytes(name.encode("utf-8"))
        rows.append(f"{name},{tags}\n")
    metadata = tmp_path / "small_multilabel_metadata.csv"
    metadata.write_text("".join(rows), encoding="utf-8")

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Small Multilabel", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        assert scan.json()["imported"] == 15

        imported = client.post(
            f"/api/datasets/{dataset['id']}/import-metadata",
            json={"file_path": str(metadata), "match_by": "relative_path", "tag_column": "tags"},
        )
        assert imported.status_code == 200
        assert imported.json()["updated"] == 15

        split = client.post(
            f"/api/datasets/{dataset['id']}/split-plan",
            json={
                "train_ratio": 70,
                "val_ratio": 30,
                "test_ratio": 10,
                "include_test": False,
                "stratify_by_tags": True,
                "normal_only": True,
                "only_unassigned": False,
                "seed": 42,
            },
        )
        assert split.status_code == 200
        payload = split.json()
        assert payload["train"] == 11
        assert payload["val"] == 4
        assert payload["test"] == 0
        assert not any("没有进入验证集" in item for item in payload["warnings"])

        for tag_name in ["father", "ng", "ok"]:
            tagged_samples = client.get(
                f"/api/datasets/{dataset['id']}/samples",
                params={"tag": tag_name, "page_size": 20},
            ).json()["items"]
            assert "val" in {sample["split"] for sample in tagged_samples}

    app.dependency_overrides.clear()


def test_v03_stratified_split_full_overlap_labels_share_one_validation_sample(tmp_path: Path):
    labels = {
        "overlap_0.png": "a;b;c",
        "overlap_1.png": "a;b;c",
        "overlap_2.png": "a;b;c",
        "overlap_3.png": "a;b;c",
        "plain_0.png": "",
        "plain_1.png": "",
    }

    with make_client() as client:
        dataset_id = create_labeled_dataset(client, tmp_path, "full_overlap", labels)
        payload = split_dataset(client, dataset_id, train_ratio=80, val_ratio=20, seed=11)

        assert payload["train"] == 5
        assert payload["val"] == 1
        assert payload["warnings"] == []
        for tag_name in ["a", "b", "c"]:
            assert "val" in sample_splits_for_tag(client, dataset_id, tag_name)

    app.dependency_overrides.clear()


def test_v03_stratified_split_warns_when_validation_capacity_cannot_cover_all_labels(tmp_path: Path):
    labels = {
        "a_0.png": "a",
        "a_1.png": "a",
        "b_0.png": "b",
        "b_1.png": "b",
        "c_0.png": "c",
        "c_1.png": "c",
        "d_0.png": "d",
        "d_1.png": "d",
        "plain_0.png": "",
        "plain_1.png": "",
    }

    with make_client() as client:
        dataset_id = create_labeled_dataset(client, tmp_path, "capacity_shortage", labels)
        payload = split_dataset(client, dataset_id, train_ratio=80, val_ratio=20, seed=42)

        assert payload["train"] == 8
        assert payload["val"] == 2
        warning_labels = {
            item.split(":", maxsplit=1)[0]
            for item in payload["warnings"]
            if "验证集只有 2 个名额" in item
        }
        assert len(warning_labels) == 2
        assert warning_labels <= {"a", "b", "c", "d"}

    app.dependency_overrides.clear()


def test_v03_stratified_split_singleton_labels_keep_cannot_guarantee_warning(tmp_path: Path):
    labels = {
        "rare_a.png": "rare_a",
        "rare_b.png": "rare_b",
        "common_0.png": "common",
        "common_1.png": "common",
        "common_2.png": "common",
        "plain_0.png": "",
    }

    with make_client() as client:
        dataset_id = create_labeled_dataset(client, tmp_path, "singleton_labels", labels)
        payload = split_dataset(client, dataset_id, train_ratio=50, val_ratio=50, seed=21)

        assert payload["train"] == 3
        assert payload["val"] == 3
        assert any(item.startswith("rare_a: 只有 1 个可处理样本") for item in payload["warnings"])
        assert any(item.startswith("rare_b: 只有 1 个可处理样本") for item in payload["warnings"])
        assert "val" in sample_splits_for_tag(client, dataset_id, "common")

    app.dependency_overrides.clear()


def test_v03_stratified_split_untagged_only_has_no_label_coverage_warnings(tmp_path: Path):
    labels = {f"plain_{index}.png": "" for index in range(7)}

    with make_client() as client:
        dataset_id = create_labeled_dataset(client, tmp_path, "untagged_only", labels)
        payload = split_dataset(client, dataset_id, train_ratio=70, val_ratio=30, seed=3)

        assert payload["train"] == 5
        assert payload["val"] == 2
        assert payload["warnings"] == []

    app.dependency_overrides.clear()


def test_v03_stratified_split_test_floor_requires_three_label_samples(tmp_path: Path):
    labels = {
        "alpha_0.png": "alpha",
        "alpha_1.png": "alpha",
        "alpha_2.png": "alpha",
        "beta_0.png": "beta",
        "beta_1.png": "beta",
        "beta_2.png": "beta",
        "alpha_beta_0.png": "alpha;beta",
        "alpha_beta_1.png": "alpha;beta",
        "plain_0.png": "",
        "plain_1.png": "",
    }

    with make_client() as client:
        dataset_id = create_labeled_dataset(client, tmp_path, "test_floor", labels)
        payload = split_dataset(
            client,
            dataset_id,
            train_ratio=60,
            val_ratio=20,
            test_ratio=20,
            include_test=True,
            seed=9,
        )

        assert payload["train"] == 6
        assert payload["val"] == 2
        assert payload["test"] == 2
        assert payload["warnings"] == []
        for tag_name in ["alpha", "beta"]:
            splits = sample_splits_for_tag(client, dataset_id, tag_name)
            assert "val" in splits
            assert "test" in splits

    app.dependency_overrides.clear()
