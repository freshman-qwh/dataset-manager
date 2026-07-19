from pathlib import Path
import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.services.annotation_geometry import (
    bbox_to_yolo_xywh,
    polygon_area,
    polygon_to_bbox,
    rectangle_to_bbox,
    rectangle_to_polygon,
)


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


def create_image_dataset(client: TestClient, tmp_path: Path, name: str = "precheck") -> tuple[int, int]:
    data_root = tmp_path / name
    data_root.mkdir()
    image_file = data_root / "sample.png"
    image_file.write_bytes(PNG_1X1)

    dataset = client.post("/api/datasets", json={"name": name, "root_path": str(data_root)}).json()
    scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
    assert scan.status_code == 200
    sample = client.get(f"/api/datasets/{dataset['id']}/samples").json()["items"][0]
    return dataset["id"], sample["id"]


def create_many_image_dataset(client: TestClient, tmp_path: Path, count: int) -> tuple[int, list[dict]]:
    data_root = tmp_path / "many-precheck"
    data_root.mkdir()
    for index in range(count):
        (data_root / f"sample_{index:03d}.png").write_bytes(PNG_1X1)

    dataset = client.post("/api/datasets", json={"name": "Many Precheck", "root_path": str(data_root)}).json()
    scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
    assert scan.status_code == 200
    samples = client.get(
        f"/api/datasets/{dataset['id']}/samples",
        params={"sort_by": "filename", "sort_order": "asc", "page_size": 200},
    ).json()["items"]
    return dataset["id"], samples


def test_annotation_geometry_bbox_area_and_yolo_normalization():
    bbox = rectangle_to_bbox([10, 20, 30, 60])
    assert bbox.width == 20
    assert bbox.height == 40
    assert bbox_to_yolo_xywh(bbox, 100, 200) == pytest.approx([0.2, 0.2, 0.2, 0.2])

    polygon_bbox = polygon_to_bbox([0, 0, 10, 0, 10, 5, 0, 5])
    assert (polygon_bbox.x_min, polygon_bbox.y_min, polygon_bbox.x_max, polygon_bbox.y_max) == (0, 0, 10, 5)
    assert polygon_area([0, 0, 10, 0, 10, 5, 0, 5]) == 50
    assert rectangle_to_polygon([0, 0, 2, 1]) == [0, 0, 2, 0, 2, 1, 0, 1]


def test_yolo_detection_precheck_warns_for_polygon_and_skips_point(tmp_path: Path):
    with make_client() as client:
        dataset_id, sample_id = create_image_dataset(client, tmp_path)
        saved = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={
                "annotations": [
                    {"label": "rect", "shape_type": "rectangle", "points": [0, 0, 1, 1]},
                    {"label": "poly", "shape_type": "polygon", "points": [0, 0, 1, 0, 1, 1]},
                    {"label": "dot", "shape_type": "point", "points": [0, 0]},
                ]
            },
        )
        assert saved.status_code == 200

        precheck = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-precheck",
            json={"format": "yolo_detection"},
        )
        assert precheck.status_code == 200
        payload = precheck.json()
        assert payload["blocked"] is False
        assert payload["sample_count"] == 1
        assert payload["annotated_sample_count"] == 1
        assert payload["exportable_object_count"] == 2
        assert payload["skipped_object_count"] == 1
        assert [item["name"] for item in payload["class_map"]] == ["poly", "rect"]
        issue_codes = {issue["code"] for issue in payload["issues"]}
        assert "POLYGON_TO_BBOX" in issue_codes
        assert "INCOMPATIBLE_SHAPE_SKIPPED" in issue_codes

    app.dependency_overrides.clear()


def test_yolo_segmentation_precheck_warns_for_rectangle(tmp_path: Path):
    with make_client() as client:
        dataset_id, sample_id = create_image_dataset(client, tmp_path)
        saved = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={
                "annotations": [
                    {"label": "rect", "shape_type": "rectangle", "points": [0, 0, 1, 1]},
                    {"label": "poly", "shape_type": "polygon", "points": [0, 0, 1, 0, 1, 1]},
                ]
            },
        )
        assert saved.status_code == 200

        precheck = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-precheck",
            json={"format": "yolo_segmentation"},
        )
        assert precheck.status_code == 200
        payload = precheck.json()
        assert payload["blocked"] is False
        assert payload["exportable_object_count"] == 2
        assert payload["warning_count"] == 1
        assert payload["issues"][0]["code"] == "RECTANGLE_TO_POLYGON"

    app.dependency_overrides.clear()


def test_detection_precheck_blocks_when_no_exportable_objects(tmp_path: Path):
    with make_client() as client:
        dataset_id, sample_id = create_image_dataset(client, tmp_path)
        saved = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [{"label": "dot", "shape_type": "point", "points": [0, 0]}]},
        )
        assert saved.status_code == 200

        precheck = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-precheck",
            json={"format": "yolo_detection"},
        )
        assert precheck.status_code == 200
        payload = precheck.json()
        assert payload["blocked"] is True
        assert payload["exportable_object_count"] == 0
        assert payload["skipped_object_count"] == 1
        assert any(issue["code"] == "NO_EXPORTABLE_OBJECTS" for issue in payload["issues"])

    app.dependency_overrides.clear()


def test_precheck_blocks_out_of_bounds_coordinates(tmp_path: Path):
    with make_client() as client:
        dataset_id, sample_id = create_image_dataset(client, tmp_path)
        saved = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [{"label": "bad", "shape_type": "rectangle", "points": [0, 0, 2, 1]}]},
        )
        assert saved.status_code == 200

        precheck = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-precheck",
            json={"format": "yolo_detection"},
        )
        assert precheck.status_code == 200
        payload = precheck.json()
        assert payload["blocked"] is True
        assert payload["exportable_object_count"] == 0
        issue_codes = {issue["code"] for issue in payload["issues"]}
        assert "COORDINATES_OUT_OF_BOUNDS" in issue_codes
        assert "NO_EXPORTABLE_OBJECTS" in issue_codes

    app.dependency_overrides.clear()


def test_precheck_prioritizes_warnings_over_empty_sample_info_when_issue_list_is_capped(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_many_image_dataset(client, tmp_path, 205)
        saved = client.put(
            f"/api/samples/{samples[-1]['id']}/annotations",
            json={"annotations": [{"label": "rect", "shape_type": "rectangle", "points": [0, 0, 1, 1]}]},
        )
        assert saved.status_code == 200

        precheck = client.post(
            f"/api/datasets/{dataset_id}/annotation-export-precheck",
            json={"format": "yolo_segmentation"},
        )
        assert precheck.status_code == 200
        payload = precheck.json()
        assert payload["warning_count"] == 1
        assert payload["info_count"] == 204
        assert payload["truncated_issue_count"] == 5
        assert len(payload["issues"]) == 200
        assert payload["issues"][0]["code"] == "RECTANGLE_TO_POLYGON"
        assert any(issue["code"] == "EMPTY_SAMPLE_SKIPPED" for issue in payload["issues"])

    app.dependency_overrides.clear()
