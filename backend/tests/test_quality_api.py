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
        assert payload["annotated_sample_count"] == 2
        assert payload["annotation_count"] == 3
        assert payload["review_status_counts"] == {
            "approved": 1,
            "in_review": 1,
            "rejected": 1,
        }
        assert payload["class_counts"] == {"defect": 2, "scratch": 1}

        issue_codes = {issue["code"] for issue in payload["issues"]}
        assert {
            "EMPTY_ANNOTATIONS",
            "DUPLICATE_ANNOTATION",
            "SPLIT_LEAKAGE",
            "RARE_CLASS",
            "CLASS_SINGLE_SPLIT",
            "REJECTED_SAMPLE",
        }.issubset(issue_codes)

        empty_issue = next(issue for issue in payload["issues"] if issue["code"] == "EMPTY_ANNOTATIONS")
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

        assert payload["check_counts"]["EMPTY_ANNOTATIONS"] == 1
        assert payload["error_count"] >= 1
        assert payload["warning_count"] >= 1
        assert payload["info_count"] >= 1

    app.dependency_overrides.clear()


def test_annotation_status_filter_lists_empty_and_annotated_images(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_quality_dataset(client, tmp_path)

        empty = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"annotation_status": "empty", "sort_by": "filename", "sort_order": "asc"},
        )
        assert empty.status_code == 200
        assert [item["id"] for item in empty.json()["items"]] == [samples["empty.png"]["id"]]

        annotated = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"annotation_status": "annotated", "sort_by": "filename", "sort_order": "asc"},
        )
        assert annotated.status_code == 200
        assert [item["filename"] for item in annotated.json()["items"]] == ["train.png", "val.png"]

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
