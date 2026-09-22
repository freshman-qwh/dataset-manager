from pathlib import Path
import base64

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


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


def test_dataset_task_type_contract_rejects_unsupported_values():
    with make_client() as client:
        created = client.post("/api/datasets", json={"name": "Workflow"})
        assert created.status_code == 201
        dataset = created.json()
        assert dataset["task_type"] == "detection"
        assert dataset["task_capabilities"]["allowed_shape_types"] == ["rectangle"]
        assert dataset["task_capabilities"]["default_export_format"] == "coco_detection"

        updated = client.patch(
            f"/api/datasets/{dataset['id']}",
            json={"task_type": "segmentation"},
        )
        assert updated.status_code == 200
        assert updated.json()["task_capabilities"]["allowed_shape_types"] == ["polygon"]

        assert client.post("/api/datasets", json={"name": "Legacy", "task_type": "tabular"}).status_code == 422
        assert client.patch(f"/api/datasets/{dataset['id']}", json={"task_type": None}).status_code == 422

    app.dependency_overrides.clear()


def test_empty_dataset_stats_return_zero_counts():
    with make_client() as client:
        created = client.post(
            "/api/datasets",
            json={"name": "Empty dataset", "task_type": "segmentation"},
        )
        assert created.status_code == 201

        response = client.get(f"/api/stats/datasets/{created.json()['id']}")

        assert response.status_code == 200
        assert response.json() == {
            "dataset_id": created.json()["id"],
            "sample_count": 0,
            "total_size": 0,
            "by_file_type": {},
            "by_extension": {},
            "by_status": {},
            "by_split": {},
            "by_annotation_progress": {},
            "by_review_status": {},
            "by_triage_status": {"untriaged": 0, "pending": 0, "ok": 0, "ng": 0},
            "by_ok_grade": {"clear": 0, "borderline": 0},
            "by_defect_severity": {"mild": 0, "moderate": 0, "severe": 0},
            "triage_outdated": 0,
            "tag_counts": {},
            "duplicate_groups": 0,
            "duplicate_samples": 0,
            "untagged_samples": 0,
            "samples_with_objects": 0,
            "annotation_count": 0,
            "by_annotation_label": {},
        }

    app.dependency_overrides.clear()


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
                "task_type": "classification",
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
        assert dataset["task_type"] == "classification"
        assert dataset["task_capabilities"] == {
            "label": "分类整理",
            "annotation_mode": "sample_tags",
            "allowed_shape_types": [],
            "default_export_format": "csv",
            "supported": True,
            "unsupported_reason": None,
        }

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


def test_sample_annotations_replace_list_and_manifest_export(tmp_path: Path):
    data_root = tmp_path / "annotated"
    data_root.mkdir()
    image_file = data_root / "sample.png"
    image_file.write_bytes(PNG_1X1)

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Annotated", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        assert scan.json()["imported"] == 1

        sample = client.get(f"/api/datasets/{dataset['id']}/samples").json()["items"][0]
        payload = {
            "save_mode": "complete",
            "annotations": [
                {
                    "label": "scratch",
                    "shape_type": "rectangle",
                    "points": [0, 0, 1, 1],
                    "attributes": {"severity": "low"},
                    "z_order": 0,
                },
                {
                    "label": "edge",
                    "shape_type": "polygon",
                    "points": [0, 0, 1, 0, 1, 1],
                    "z_order": 1,
                    "notes": "corner area",
                },
            ]
        }

        saved = client.put(f"/api/samples/{sample['id']}/annotations", json=payload)
        assert saved.status_code == 200
        saved_payload = saved.json()
        assert [item["label"] for item in saved_payload] == ["scratch", "edge"]
        assert saved_payload[0]["attributes"] == {"severity": "low"}

        listed = client.get(f"/api/samples/{sample['id']}/annotations")
        assert listed.status_code == 200
        assert len(listed.json()) == 2

        refreshed_sample = client.get(f"/api/samples/{sample['id']}").json()
        assert refreshed_sample["review_status"] == "in_review"
        assert refreshed_sample["annotation_progress"] == "completed_with_objects"
        assert refreshed_sample["tags"] == []

        stats = client.get(f"/api/stats/datasets/{dataset['id']}").json()
        assert stats["tag_counts"] == {}
        assert stats["samples_with_objects"] == 1
        assert stats["by_annotation_progress"]["completed_with_objects"] == 1
        assert stats["annotation_count"] == 2
        assert stats["by_annotation_label"] == {"scratch": 1, "edge": 1}
        filtered_by_annotation_label = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"tag": "scratch"},
        ).json()
        assert filtered_by_annotation_label["total"] == 0

        annotation_classes = client.get(f"/api/datasets/{dataset['id']}/annotation-classes").json()
        assert {item["name"] for item in annotation_classes} == {"scratch", "edge"}
        synced = client.post(f"/api/samples/{sample['id']}/annotations/sync-sample-tags")
        assert synced.status_code == 200
        assert set(synced.json()["added_tags"]) == {"scratch", "edge"}
        refreshed_sample = client.get(f"/api/samples/{sample['id']}").json()
        assert {tag["name"] for tag in refreshed_sample["tags"]} == {"scratch", "edge"}
        filtered_by_sample_tag = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"tag": "scratch"},
        ).json()
        assert filtered_by_sample_tag["total"] == 1

        manifest = client.get(f"/api/datasets/{dataset['id']}/export-manifest").json()
        annotations = manifest["samples"][0]["annotations"]
        assert annotations[0]["label"] == "scratch"
        assert annotations[0]["shape_type"] == "rectangle"
        assert annotations[1]["notes"] == "corner area"

        labelme = client.post(f"/api/samples/{sample['id']}/annotations/export-labelme")
        assert labelme.status_code == 200
        assert labelme.json()["imagePath"] == "sample.png"
        assert labelme.json()["imageWidth"] == 1
        assert labelme.json()["shapes"][0]["points"] == [[0.0, 0.0], [1.0, 1.0]]

        tags = client.get(f"/api/datasets/{dataset['id']}/tags").json()
        assert {tag["name"] for tag in tags} >= {"scratch", "edge"}

    app.dependency_overrides.clear()


def test_duplicate_sample_filter_groups_hashes_together(tmp_path: Path):
    data_root = tmp_path / "duplicate-groups"
    data_root.mkdir()
    payloads = {
        "a_first.png": b"group-a",
        "b_first.png": b"group-b",
        "c_second.png": b"group-a",
        "d_second.png": b"group-b",
        "unique.png": b"unique",
    }
    for filename, content in payloads.items():
        (data_root / filename).write_bytes(content)

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Duplicate Groups", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200

        duplicate_filtered = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"file_status": "duplicate", "sort_by": "filename", "sort_order": "asc", "page_size": 10},
        )
        assert duplicate_filtered.status_code == 200
        items = duplicate_filtered.json()["items"]
        hashes = [item["file_hash"] for item in items]
        assert len(items) == 4
        assert hashes[0] == hashes[1]
        assert hashes[2] == hashes[3]
        assert hashes[1] != hashes[2]
        assert {item["file_status"] for item in items} == {"normal"}

    app.dependency_overrides.clear()


def test_duplicate_report_explains_cross_split_leakage_and_paginates(tmp_path: Path):
    data_root = tmp_path / "duplicate-leakage"
    data_root.mkdir()
    payloads = {
        "a_train.png": b"leak-a",
        "a_val.png": b"leak-a",
        "b_val.png": b"leak-b",
        "b_test.png": b"leak-b",
        "b_unassigned.png": b"leak-b",
        "c_train_first.png": b"same-split",
        "c_train_second.png": b"same-split",
        "d_train.png": b"assigned-and-unassigned",
        "d_unassigned.png": b"assigned-and-unassigned",
        "unique.png": b"unique",
    }
    for filename, content in payloads.items():
        (data_root / filename).write_bytes(content)
    original_contents = {path.name: path.read_bytes() for path in data_root.iterdir()}

    with make_client() as client:
        dataset = client.post(
            "/api/datasets",
            json={"name": "Duplicate leakage", "root_path": str(data_root)},
        ).json()
        scan = client.post(
            f"/api/datasets/{dataset['id']}/scan",
            json={"folder_path": str(data_root)},
        )
        assert scan.status_code == 200

        samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"page_size": 20},
        ).json()["items"]
        samples_by_name = {sample["filename"]: sample for sample in samples}
        splits = {
            "a_train.png": "train",
            "a_val.png": "val",
            "b_val.png": "val",
            "b_test.png": "test",
            "c_train_first.png": "train",
            "c_train_second.png": "train",
            "d_train.png": "train",
        }
        for filename, split_name in splits.items():
            response = client.patch(
                f"/api/samples/{samples_by_name[filename]['id']}",
                json={"split": split_name},
            )
            assert response.status_code == 200

        first_page = client.get(
            f"/api/datasets/{dataset['id']}/duplicates",
            params={"page": 1, "page_size": 2},
        )
        assert first_page.status_code == 200
        report = first_page.json()
        assert report["group_count"] == 4
        assert report["duplicate_sample_count"] == 9
        assert report["cross_split_group_count"] == 2
        assert report["cross_split_sample_count"] == 5
        assert report["filtered_group_count"] == 4
        assert report["has_previous"] is False
        assert report["has_next"] is True
        assert len(report["groups"]) == 2
        assert all(group["cross_split"] for group in report["groups"])

        three_sample_group = next(group for group in report["groups"] if group["count"] == 3)
        assert three_sample_group["training_splits"] == ["val", "test"]
        assert three_sample_group["split_counts"] == {"test": 1, "unassigned": 1, "val": 1}
        assert {sample["filename"] for sample in three_sample_group["samples"]} == {
            "b_test.png",
            "b_unassigned.png",
            "b_val.png",
        }

        leakage_page = client.get(
            f"/api/datasets/{dataset['id']}/duplicates",
            params={"leakage_only": True, "page": 99, "page_size": 1},
        )
        assert leakage_page.status_code == 200
        leakage_report = leakage_page.json()
        assert leakage_report["filtered_group_count"] == 2
        assert leakage_report["page"] == 2
        assert leakage_report["has_previous"] is True
        assert leakage_report["has_next"] is False
        assert len(leakage_report["groups"]) == 1
        assert leakage_report["groups"][0]["training_splits"] == ["train", "val"]

        target_hash = leakage_report["groups"][0]["file_hash"]
        located = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"file_status": "duplicate", "search": target_hash, "page_size": 20},
        )
        assert located.status_code == 200
        assert located.json()["total"] == 2
        assert {item["filename"] for item in located.json()["items"]} == {
            "a_train.png",
            "a_val.png",
        }

        assert client.get(
            f"/api/datasets/{dataset['id']}/duplicates",
            params={"page_size": 101},
        ).status_code == 422
        assert {path.name: path.read_bytes() for path in data_root.iterdir()} == original_contents

    app.dependency_overrides.clear()


def test_sample_navigation_uses_context_and_skips_non_normal_images(tmp_path: Path):
    data_root = tmp_path / "navigation"
    data_root.mkdir()
    for filename in ["a.png", "b.png", "c.png"]:
        (data_root / filename).write_bytes(PNG_1X1)
    (data_root / "rows.csv").write_text("id,value\n1,2\n", encoding="utf-8")

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Navigation", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200
        (data_root / "b.png").unlink()
        rescan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert rescan.status_code == 200

        navigation = client.get(
            f"/api/datasets/{dataset['id']}/samples/navigation",
            params={"sort_by": "filename", "sort_order": "asc"},
        )
        assert navigation.status_code == 200
        payload = navigation.json()
        assert payload["total"] == 2
        assert payload["remaining"] == 1
        assert payload["queue_scope"] == "current_filter"
        assert payload["current_index"] == 0
        assert payload["current_sample"]["filename"] == "a.png"
        assert payload["previous_sample"] is None
        assert payload["next_sample"]["filename"] == "c.png"

        second_navigation = client.get(
            f"/api/datasets/{dataset['id']}/samples/navigation",
            params={
                "sample_id": payload["next_sample"]["id"],
                "sort_by": "filename",
                "sort_order": "asc",
            },
        ).json()
        assert second_navigation["current_index"] == 1
        assert second_navigation["remaining"] == 1
        assert second_navigation["previous_sample"]["filename"] == "a.png"
        assert second_navigation["next_sample"] is None

    app.dependency_overrides.clear()


def test_sample_navigation_supports_pending_filter_and_split_queues(tmp_path: Path):
    data_root = tmp_path / "navigation-queues"
    data_root.mkdir()
    for filename in ["a.png", "b.png", "c.png", "d.png"]:
        (data_root / filename).write_bytes(PNG_1X1)

    with make_client() as client:
        dataset = client.post(
            "/api/datasets",
            json={"name": "Navigation queues", "root_path": str(data_root)},
        ).json()
        assert client.post(
            f"/api/datasets/{dataset['id']}/scan",
            json={"folder_path": str(data_root)},
        ).status_code == 200
        samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"sort_by": "filename", "sort_order": "asc"},
        ).json()["items"]
        by_name = {sample["filename"]: sample for sample in samples}

        for filename, split, progress in [
            ("a.png", "train", "not_started"),
            ("b.png", "train", "in_progress"),
            ("c.png", "train", "completed_with_objects"),
            ("d.png", "val", "not_started"),
        ]:
            response = client.patch(
                f"/api/samples/{by_name[filename]['id']}",
                json={"split": split, "annotation_progress": progress},
            )
            assert response.status_code == 200

        all_pending = client.get(
            f"/api/datasets/{dataset['id']}/samples/navigation",
            params={
                "queue_scope": "all_pending",
                "search": "d.png",
                "split": "val",
                "sort_by": "filename",
                "sort_order": "asc",
            },
        ).json()
        assert all_pending["queue_scope"] == "all_pending"
        assert all_pending["total"] == 3
        assert all_pending["remaining"] == 2
        assert all_pending["current_sample"]["filename"] == "a.png"
        assert all_pending["next_sample"]["filename"] == "b.png"

        current_filter = client.get(
            f"/api/datasets/{dataset['id']}/samples/navigation",
            params={
                "queue_scope": "current_filter",
                "search": "d.png",
                "sort_by": "filename",
                "sort_order": "asc",
            },
        ).json()
        assert current_filter["total"] == 1
        assert current_filter["remaining"] == 0
        assert current_filter["current_sample"]["filename"] == "d.png"

        current_split = client.get(
            f"/api/datasets/{dataset['id']}/samples/navigation",
            params={
                "queue_scope": "current_split",
                "sample_id": by_name["b.png"]["id"],
                "search": "d.png",
                "review_status": "approved",
                "annotation_progress": "completed_with_objects",
                "sort_by": "filename",
                "sort_order": "asc",
            },
        ).json()
        assert current_split["queue_scope"] == "current_split"
        assert current_split["total"] == 2
        assert current_split["current_index"] == 1
        assert current_split["remaining"] == 1
        assert current_split["previous_sample"]["filename"] == "a.png"

        completed_outside_queue = client.get(
            f"/api/datasets/{dataset['id']}/samples/navigation",
            params={
                "queue_scope": "current_split",
                "sample_id": by_name["c.png"]["id"],
                "sort_by": "filename",
                "sort_order": "asc",
            },
        ).json()
        assert completed_outside_queue["total"] == 2
        assert completed_outside_queue["current_index"] is None
        assert completed_outside_queue["remaining"] == 2
        assert completed_outside_queue["current_sample"] is None

    app.dependency_overrides.clear()


def test_sample_annotations_validate_shape_and_image_type(tmp_path: Path):
    data_root = tmp_path / "annotation-validation"
    data_root.mkdir()
    table_file = data_root / "rows.csv"
    table_file.write_text("id,value\n1,2\n", encoding="utf-8")
    image_file = data_root / "sample.png"
    image_file.write_bytes(PNG_1X1)

    with make_client() as client:
        dataset = client.post("/api/datasets", json={"name": "Validation", "root_path": str(data_root)}).json()
        scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
        assert scan.status_code == 200

        samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"sort_by": "filename", "sort_order": "asc"},
        ).json()["items"]
        table_sample = next(sample for sample in samples if sample["file_type"] == "table")
        image_sample = next(sample for sample in samples if sample["file_type"] == "image")

        rejected_type = client.put(
            f"/api/samples/{table_sample['id']}/annotations",
            json={"annotations": [{"label": "bad", "shape_type": "point", "points": [1, 1]}]},
        )
        assert rejected_type.status_code == 400

        rejected_shape = client.put(
            f"/api/samples/{image_sample['id']}/annotations",
            json={"annotations": [{"label": "bad", "shape_type": "rectangle", "points": [1, 1, 0, 0]}]},
        )
        assert rejected_shape.status_code == 400

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
        assert stats.json()["untagged_samples"] == 0

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
        assert samples[0]["review_status"] == "not_reviewed"
        assert samples[0]["annotation_progress"] == "not_started"

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
        assert stats["untagged_samples"] == 2

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
