from collections import Counter
from io import BytesIO
from pathlib import Path
import struct
from xml.etree import ElementTree
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.services.quality_service import _IssueCollector, _check_class_distribution


def png_bytes(width: int, height: int) -> bytes:
    payload = bytearray(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00"
    )
    payload[16:24] = struct.pack(">II", width, height)
    return bytes(payload)


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


def create_quality_dataset(client: TestClient, tmp_path: Path) -> tuple[int, dict[str, dict]]:
    data_root = tmp_path / "quality-dataset"
    data_root.mkdir()
    (data_root / "train.png").write_bytes(png_bytes(10, 10))
    # Keep the same bytes so the train/val split creates an exact leakage group.
    (data_root / "val.png").write_bytes((data_root / "train.png").read_bytes())
    (data_root / "empty.png").write_bytes(png_bytes(12, 10))

    dataset = client.post(
        "/api/datasets",
        json={"name": "Quality Dataset", "root_path": str(data_root)},
    ).json()
    scan = client.post(
        f"/api/datasets/{dataset['id']}/scan",
        json={"folder_path": str(data_root)},
    )
    assert scan.status_code == 200
    response = client.get(
        f"/api/datasets/{dataset['id']}/samples",
        params={"sort_by": "filename", "sort_order": "asc", "page_size": 20},
    )
    samples = {item["filename"]: item for item in response.json()["items"]}
    assert set(samples) == {"empty.png", "train.png", "val.png"}

    assert client.patch(
        f"/api/samples/{samples['train.png']['id']}",
        json={"split": "train", "review_status": "in_review"},
    ).status_code == 200
    assert client.patch(
        f"/api/samples/{samples['val.png']['id']}",
        json={"split": "val", "review_status": "approved"},
    ).status_code == 200
    assert client.patch(
        f"/api/samples/{samples['empty.png']['id']}",
        json={"split": "test", "review_status": "rejected"},
    ).status_code == 200

    duplicate_objects = [
        {"label": "defect", "shape_type": "rectangle", "points": [1, 1, 6, 6]},
        {"label": "defect", "shape_type": "rectangle", "points": [1, 1, 6, 6]},
    ]
    assert client.put(
        f"/api/samples/{samples['train.png']['id']}/annotations",
        json={"annotations": duplicate_objects, "review_status": "in_review"},
    ).status_code == 200
    assert client.put(
        f"/api/samples/{samples['val.png']['id']}/annotations",
        json={
            "annotations": [
                {
                    "label": "scratch",
                    "shape_type": "polygon",
                    "points": [1, 1, 8, 1, 8, 8, 1, 8],
                    "attributes": {"occluded": True, "truncated": True, "difficult": True},
                }
            ],
            "review_status": "approved",
        },
    ).status_code == 200
    return dataset["id"], samples


def test_quality_report_unifies_annotation_split_distribution_and_review_checks(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_quality_dataset(client, tmp_path)

        response = client.get(f"/api/datasets/{dataset_id}/quality-report")
        assert response.status_code == 200
        payload = response.json()

        assert payload["dataset_id"] == dataset_id
        assert payload["image_sample_count"] == 3
        assert payload["samples_with_objects_count"] == 2
        assert payload["confirmed_empty_sample_count"] == 0
        assert payload["annotation_count"] == 3
        assert payload["review_status_counts"] == {
            "approved": 1,
            "in_review": 1,
            "rejected": 1,
        }
        assert payload["class_counts"] == {"defect": 2, "scratch": 1}

        issue_codes = {issue["code"] for issue in payload["issues"]}
        assert {
            "ANNOTATION_NOT_STARTED",
            "DUPLICATE_ANNOTATION",
            "SPLIT_LEAKAGE",
            "RARE_CLASS",
            "CLASS_SINGLE_SPLIT",
            "REJECTED_SAMPLE",
            "TASK_SHAPE_MISMATCH",
        }.issubset(issue_codes)

        empty_issue = next(issue for issue in payload["issues"] if issue["code"] == "ANNOTATION_NOT_STARTED")
        assert empty_issue["sample_id"] == samples["empty.png"]["id"]
        assert empty_issue["sample_path"] == "empty.png"
        duplicate_issue = next(issue for issue in payload["issues"] if issue["code"] == "DUPLICATE_ANNOTATION")
        assert duplicate_issue["sample_id"] == samples["train.png"]["id"]
        assert len(duplicate_issue["related_annotation_ids"]) == 2
        leakage_issue = next(issue for issue in payload["issues"] if issue["code"] == "SPLIT_LEAKAGE")
        assert set(leakage_issue["related_sample_ids"]) == {
            samples["train.png"]["id"],
            samples["val.png"]["id"],
        }

        assert payload["check_counts"]["ANNOTATION_NOT_STARTED"] == 1
        assert payload["check_counts"]["TASK_SHAPE_MISMATCH"] == 1
        assert payload["error_count"] >= 1
        assert payload["warning_count"] >= 1
        assert payload["info_count"] >= 1

    app.dependency_overrides.clear()


def test_classification_quality_uses_sample_tags_instead_of_geometry_progress(tmp_path: Path):
    data_root = tmp_path / "classification-quality"
    data_root.mkdir()
    (data_root / "labeled.png").write_bytes(png_bytes(10, 10))
    (data_root / "pending.png").write_bytes(png_bytes(12, 10))

    with make_client() as client:
        dataset = client.post(
            "/api/datasets",
            json={
                "name": "Classification Quality",
                "root_path": str(data_root),
                "task_type": "classification",
            },
        ).json()
        assert client.post(
            f"/api/datasets/{dataset['id']}/scan",
            json={"folder_path": str(data_root)},
        ).status_code == 200
        samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"sort_by": "filename", "sort_order": "asc", "page_size": 20},
        ).json()["items"]
        assert client.patch(
            f"/api/samples/{samples[0]['id']}",
            json={"tags": ["accepted"]},
        ).status_code == 200

        response = client.get(f"/api/datasets/{dataset['id']}/quality-report")
        assert response.status_code == 200
        payload = response.json()

        assert payload["samples_with_objects_count"] == 1
        assert payload["confirmed_empty_sample_count"] == 0
        assert payload["class_counts"] == {"accepted": 1}
        assert payload["check_counts"]["SAMPLE_TAG_MISSING"] == 1
        assert "ANNOTATION_NOT_STARTED" not in payload["check_counts"]

    app.dependency_overrides.clear()


def test_training_readiness_summarizes_completion_review_split_and_format(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_quality_dataset(client, tmp_path)
        train_sample_id = samples["train.png"]["id"]
        empty_sample_id = samples["empty.png"]["id"]

        assert client.put(
            f"/api/samples/{train_sample_id}/annotations",
            json={
                "annotations": [
                    {"label": "defect", "shape_type": "rectangle", "points": [1, 1, 6, 6]}
                ],
                "save_mode": "complete",
            },
        ).status_code == 200
        assert client.put(
            f"/api/samples/{empty_sample_id}/annotations",
            json={"annotations": [], "save_mode": "confirm_empty"},
        ).status_code == 200

        response = client.get(f"/api/datasets/{dataset_id}/training-readiness")
        assert response.status_code == 200
        payload = response.json()

        assert payload["dataset_id"] == dataset_id
        assert payload["task_type"] == "detection"
        assert payload["status"] == "blocked"
        assert payload["recommended_export_format"] == "coco_detection"
        assert payload["compatible_export_formats"] == [
            "coco_detection",
            "yolo_detection",
            "voc",
        ]
        assert payload["scoped_sample_count"] == 3
        assert payload["completed_sample_count"] == 2
        assert payload["confirmed_empty_sample_count"] == 1
        assert payload["pending_sample_count"] == 1
        assert payload["pending_review_count"] == 1
        assert payload["rejected_sample_count"] == 1
        assert payload["blocking_issue_count"] >= 1
        assert payload["suggested_fix_count"] >= 1
        assert payload["notice_count"] >= 1
        assert payload["truncated_issue_count"] == 0
        assert len(payload["issues"]) == (
            payload["blocking_issue_count"]
            + payload["suggested_fix_count"]
            + payload["notice_count"]
        )
        assert payload["issues"][0]["severity"] == "error"
        assert payload["issues"][0]["code"]
        assert payload["issues"][0]["title"]
        assert payload["issues"][0]["message"]
        assert payload["split_counts"] == {"test": 1, "train": 1, "val": 1}
        assert payload["split_covered_sample_count"] == 3
        assert payload["split_coverage_percent"] == 100.0
        assert payload["last_export_at"] is None
        assert payload["last_config"] is None

    app.dependency_overrides.clear()


def test_training_readiness_persists_config_and_last_export(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_quality_dataset(client, tmp_path)
        selected_sample_id = samples["train.png"]["id"]
        config = {
            "format": "coco_detection",
            "scope": "selected",
            "split": None,
            "include_empty": True,
            "sample_query": {
                "sample_ids": [selected_sample_id],
                "sort_by": "relative_path",
                "sort_order": "asc",
            },
            "class_map": [
                {"name": "defect", "id": 1, "coco_id": 1, "yolo_id": 0},
            ],
        }

        saved_response = client.put(
            f"/api/datasets/{dataset_id}/training-readiness/config",
            json=config,
        )
        assert saved_response.status_code == 200
        saved = saved_response.json()
        assert saved["task_type"] == "detection"
        assert saved["format"] == "coco_detection"
        assert saved["scope"] == "selected"
        assert saved["sample_query"]["sample_ids"] == [selected_sample_id]
        assert saved["class_map"][0]["name"] == "defect"
        assert saved["last_export_at"] is None
        assert saved["saved_at"].endswith("Z") or saved["saved_at"].endswith("+00:00")

        readiness = client.get(
            f"/api/datasets/{dataset_id}/training-readiness"
        ).json()
        assert readiness["last_config"] == saved
        assert readiness["last_export_at"] is None

        exported_response = client.post(
            f"/api/datasets/{dataset_id}/training-readiness/exports",
            json=config,
        )
        assert exported_response.status_code == 200
        exported = exported_response.json()
        assert exported["last_export_at"] is not None
        assert exported["last_export_at"].endswith("Z") or exported[
            "last_export_at"
        ].endswith("+00:00")

        updated_config = {
            **config,
            "format": "yolo_detection",
            "scope": "split",
            "split": "train",
            "sample_query": {
                "split": "val",
                "sort_by": "relative_path",
                "sort_order": "asc",
            },
        }
        updated_response = client.put(
            f"/api/datasets/{dataset_id}/training-readiness/config",
            json=updated_config,
        )
        assert updated_response.status_code == 200
        updated = updated_response.json()
        assert updated["format"] == "yolo_detection"
        assert updated["split"] == "train"
        assert updated["sample_query"]["split"] == "train"
        assert updated["last_export_at"] == exported["last_export_at"]

        refreshed = client.get(
            f"/api/datasets/{dataset_id}/training-readiness"
        ).json()
        assert refreshed["last_config"] == updated
        assert refreshed["last_export_at"] == exported["last_export_at"]

    app.dependency_overrides.clear()


def test_training_readiness_rejects_incompatible_or_incomplete_config(tmp_path: Path):
    with make_client() as client:
        dataset_id, _ = create_quality_dataset(client, tmp_path)
        base_config = {
            "format": "coco_detection",
            "scope": "all",
            "include_empty": False,
            "sample_query": {},
            "class_map": [],
        }

        incompatible = client.put(
            f"/api/datasets/{dataset_id}/training-readiness/config",
            json={**base_config, "format": "csv"},
        )
        assert incompatible.status_code == 422
        assert "not available" in incompatible.json()["detail"]

        missing_split = client.put(
            f"/api/datasets/{dataset_id}/training-readiness/config",
            json={**base_config, "scope": "split"},
        )
        assert missing_split.status_code == 422
        assert "split is required" in missing_split.json()["detail"]

        empty_selection = client.put(
            f"/api/datasets/{dataset_id}/training-readiness/config",
            json={**base_config, "scope": "selected"},
        )
        assert empty_selection.status_code == 422
        assert "At least one sample" in empty_selection.json()["detail"]

        foreign_selection = client.put(
            f"/api/datasets/{dataset_id}/training-readiness/config",
            json={
                **base_config,
                "scope": "selected",
                "sample_query": {"sample_ids": [999999]},
            },
        )
        assert foreign_selection.status_code == 422
        assert "target dataset" in foreign_selection.json()["detail"]

    app.dependency_overrides.clear()


def test_classification_training_readiness_records_csv_export():
    with make_client() as client:
        dataset = client.post(
            "/api/datasets",
            json={"name": "Classification Training", "task_type": "classification"},
        ).json()
        config = {
            "format": "csv",
            "scope": "all",
            "include_empty": False,
            "sample_query": {
                "sort_by": "relative_path",
                "sort_order": "asc",
            },
            "class_map": [],
        }

        saved = client.put(
            f"/api/datasets/{dataset['id']}/training-readiness/config",
            json=config,
        )
        assert saved.status_code == 200
        assert saved.json()["task_type"] == "classification"
        assert saved.json()["format"] == "csv"

        exported = client.post(
            f"/api/datasets/{dataset['id']}/training-readiness/exports",
            json=config,
        )
        assert exported.status_code == 200
        assert exported.json()["last_export_at"] is not None

        incompatible = client.put(
            f"/api/datasets/{dataset['id']}/training-readiness/config",
            json={**config, "format": "coco_detection"},
        )
        assert incompatible.status_code == 422

    app.dependency_overrides.clear()


def test_tagged_and_untagged_virtual_filters_return_exact_classification_ranges(tmp_path: Path):
    data_root = tmp_path / "classification-filter"
    data_root.mkdir()
    (data_root / "labeled.png").write_bytes(png_bytes(10, 10))
    (data_root / "pending.png").write_bytes(png_bytes(12, 10))

    with make_client() as client:
        dataset = client.post(
            "/api/datasets",
            json={
                "name": "Classification Filter",
                "root_path": str(data_root),
                "task_type": "classification",
            },
        ).json()
        assert client.post(
            f"/api/datasets/{dataset['id']}/scan",
            json={"folder_path": str(data_root)},
        ).status_code == 200
        samples = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"sort_by": "filename", "sort_order": "asc"},
        ).json()["items"]
        assert client.patch(
            f"/api/samples/{samples[0]['id']}",
            json={"tags": ["accepted"]},
        ).status_code == 200

        tagged = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"tag": "__tagged__", "sort_by": "filename", "sort_order": "asc"},
        )
        untagged = client.get(
            f"/api/datasets/{dataset['id']}/samples",
            params={"tag": "__untagged__", "sort_by": "filename", "sort_order": "asc"},
        )

        assert tagged.status_code == 200
        assert [item["filename"] for item in tagged.json()["items"]] == ["labeled.png"]
        assert untagged.status_code == 200
        assert [item["filename"] for item in untagged.json()["items"]] == ["pending.png"]

    app.dependency_overrides.clear()


def test_annotation_progress_filter_is_independent_from_objects_and_review(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_quality_dataset(client, tmp_path)

        not_started = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"annotation_progress": "not_started", "sort_by": "filename", "sort_order": "asc"},
        )
        assert not_started.status_code == 200
        assert [item["id"] for item in not_started.json()["items"]] == [samples["empty.png"]["id"]]

        in_progress = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"annotation_progress": "in_progress", "sort_by": "filename", "sort_order": "asc"},
        )
        assert in_progress.status_code == 200
        assert [item["filename"] for item in in_progress.json()["items"]] == ["train.png", "val.png"]

    app.dependency_overrides.clear()


def test_annotation_save_rejects_out_of_bounds_and_zero_area_polygon(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_quality_dataset(client, tmp_path)
        sample_id = samples["train.png"]["id"]

        out_of_bounds = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [{"label": "bad", "shape_type": "rectangle", "points": [0, 0, 11, 10]}]},
        )
        assert out_of_bounds.status_code == 400
        assert "image bounds" in out_of_bounds.json()["detail"]

        zero_area = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [{"label": "bad", "shape_type": "polygon", "points": [1, 1, 2, 2, 3, 3]}]},
        )
        assert zero_area.status_code == 400
        assert "positive area" in zero_area.json()["detail"]

        # A rejected replacement must leave the prior annotations untouched.
        current = client.get(f"/api/samples/{sample_id}/annotations")
        assert current.status_code == 200
        assert len(current.json()) == 2

    app.dependency_overrides.clear()


def test_standard_object_attributes_round_trip_and_export(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_quality_dataset(client, tmp_path)
        sample_id = samples["val.png"]["id"]

        annotations = client.get(f"/api/samples/{sample_id}/annotations").json()
        assert annotations[0]["attributes"] == {
            "occluded": True,
            "truncated": True,
            "difficult": True,
        }

        labelme = client.post(f"/api/samples/{sample_id}/annotations/export-labelme")
        assert labelme.status_code == 200
        assert labelme.json()["shapes"][0]["flags"] == {
            "occluded": True,
            "truncated": True,
            "difficult": True,
        }

        coco = client.get(
            f"/api/datasets/{dataset_id}/annotation-export",
            params={"format": "coco_segmentation", "sample_ids": sample_id},
        )
        assert coco.status_code == 200
        assert coco.json()["annotations"][0]["attributes"] == {
            "occluded": True,
            "truncated": True,
            "difficult": True,
        }

        voc = client.get(
            f"/api/datasets/{dataset_id}/annotation-export",
            params={"format": "voc", "sample_ids": sample_id},
        )
        assert voc.status_code == 200
        with ZipFile(BytesIO(voc.content)) as archive:
            root = ElementTree.fromstring(archive.read("annotations/val.xml"))
            node = root.find("object")
            assert node is not None
            assert node.findtext("occluded") == "1"
            assert node.findtext("truncated") == "1"
            assert node.findtext("difficult") == "1"

    app.dependency_overrides.clear()


def test_class_distribution_check_reports_large_relative_split_shift():
    issues = _IssueCollector(limit=20)
    _check_class_distribution(
        Counter({"left-heavy": 10, "right-heavy": 10}),
        {
            "train": Counter({"left-heavy": 9, "right-heavy": 1}),
            "val": Counter({"left-heavy": 1, "right-heavy": 9}),
        },
        issues,
    )

    assert issues.code_counts["CLASS_SPLIT_IMBALANCE"] == 2
    assert all(issue.severity == "warning" for issue in issues.visible())


def test_class_distribution_ignores_unassigned_objects_in_split_ratio():
    issues = _IssueCollector(limit=20)
    _check_class_distribution(
        Counter({"balanced": 100}),
        {
            "train": Counter({"balanced": 5}),
            "val": Counter({"balanced": 5}),
            "unassigned": Counter({"balanced": 90}),
        },
        issues,
    )

    assert issues.code_counts["CLASS_SPLIT_IMBALANCE"] == 0
