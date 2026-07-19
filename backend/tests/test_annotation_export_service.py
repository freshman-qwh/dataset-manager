from io import BytesIO
import json
from pathlib import Path
import struct
from xml.etree import ElementTree
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app


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


def png_bytes(width: int, height: int) -> bytes:
    payload = bytearray(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00"
    )
    payload[16:24] = struct.pack(">II", width, height)
    return bytes(payload)


def create_export_dataset(client: TestClient, tmp_path: Path) -> tuple[int, dict[str, dict]]:
    data_root = tmp_path / "export-dataset"
    nested = data_root / "nested"
    nested.mkdir(parents=True)
    (data_root / "a.png").write_bytes(png_bytes(100, 80))
    (nested / "b.png").write_bytes(png_bytes(200, 100))
    (data_root / "empty.png").write_bytes(png_bytes(64, 64))

    dataset_response = client.post(
        "/api/datasets",
        json={"name": "Export Dataset", "root_path": str(data_root)},
    )
    assert dataset_response.status_code == 201
    dataset_id = dataset_response.json()["id"]
    scan_response = client.post(
        f"/api/datasets/{dataset_id}/scan",
        json={"folder_path": str(data_root)},
    )
    assert scan_response.status_code == 200

    samples_response = client.get(
        f"/api/datasets/{dataset_id}/samples",
        params={"sort_by": "relative_path", "sort_order": "asc", "page_size": 20},
    )
    samples = {item["filename"]: item for item in samples_response.json()["items"]}
    assert set(samples) == {"a.png", "b.png", "empty.png"}

    assert client.patch(f"/api/samples/{samples['a.png']['id']}", json={"split": "train"}).status_code == 200
    assert client.patch(f"/api/samples/{samples['b.png']['id']}", json={"split": "val"}).status_code == 200

    annotations_by_filename = {
        "a.png": [
            {"label": "defect", "shape_type": "rectangle", "points": [10, 20, 40, 60]},
            {"label": "scratch", "shape_type": "polygon", "points": [50, 10, 90, 10, 80, 50, 50, 40]},
            {"label": "ignored-point", "shape_type": "point", "points": [5, 5]},
        ],
        "b.png": [
            {"label": "scratch", "shape_type": "rectangle", "points": [20, 10, 60, 40]},
            {"label": "defect", "shape_type": "polygon", "points": [100, 20, 160, 20, 150, 70, 110, 60]},
        ],
    }
    for filename, annotations in annotations_by_filename.items():
        response = client.put(
            f"/api/samples/{samples[filename]['id']}/annotations",
            json={"annotations": annotations},
        )
        assert response.status_code == 200

    return dataset_id, samples


def export_response(client: TestClient, dataset_id: int, export_format: str, **params):
    query = [("format", export_format)]
    for key, value in params.items():
        if isinstance(value, list):
            query.extend((key, item) for item in value)
        else:
            query.append((key, value))
    return client.get(f"/api/datasets/{dataset_id}/annotation-export", params=query)


def test_coco_detection_export_has_stable_ids_and_bbox_contract(tmp_path: Path):
    with make_client() as client:
        dataset_id, _ = create_export_dataset(client, tmp_path)
        response = export_response(client, dataset_id, "coco_detection")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert "coco-detection.json" in response.headers["content-disposition"]
        payload = response.json()
        assert payload["info"]["description"] == "Export Dataset"
        assert payload["licenses"] == []
        assert payload["categories"] == [
            {"id": 1, "name": "defect", "supercategory": "object"},
            {"id": 2, "name": "scratch", "supercategory": "object"},
        ]
        assert [item["file_name"] for item in payload["images"]] == ["a.png", "nested/b.png"]
        assert [item["id"] for item in payload["images"]] == [1, 2]
        assert len(payload["annotations"]) == 4

        first = payload["annotations"][0]
        assert first == {
            "id": 1,
            "image_id": 1,
            "category_id": 1,
            "bbox": [10.0, 20.0, 30.0, 40.0],
            "area": 1200.0,
            "segmentation": [],
            "iscrowd": 0,
        }
        polygon = payload["annotations"][1]
        assert polygon["bbox"] == [50.0, 10.0, 40.0, 40.0]
        assert polygon["area"] == 1600.0
        assert payload["dataset_manager"]["exported_object_count"] == 4
        assert payload["dataset_manager"]["skipped_object_count"] == 1

    app.dependency_overrides.clear()


def test_coco_segmentation_exports_polygon_and_rectangle_segments(tmp_path: Path):
    with make_client() as client:
        dataset_id, _ = create_export_dataset(client, tmp_path)
        response = export_response(client, dataset_id, "coco_segmentation")

        assert response.status_code == 200
        payload = response.json()
        rectangle = payload["annotations"][0]
        assert rectangle["segmentation"] == [[10.0, 20.0, 40.0, 20.0, 40.0, 60.0, 10.0, 60.0]]
        assert rectangle["area"] == 1200.0
        polygon = payload["annotations"][1]
        assert polygon["segmentation"] == [[50.0, 10.0, 90.0, 10.0, 80.0, 50.0, 50.0, 40.0]]
        assert polygon["bbox"] == [50.0, 10.0, 40.0, 40.0]
        assert polygon["area"] == 1250.0
        assert all(item["iscrowd"] == 0 for item in payload["annotations"])

    app.dependency_overrides.clear()


def test_yolo_detection_export_contains_normalized_labels_and_report(tmp_path: Path):
    with make_client() as client:
        dataset_id, _ = create_export_dataset(client, tmp_path)
        response = export_response(client, dataset_id, "yolo_detection")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with ZipFile(BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            assert names == {
                "labels/train/a.txt",
                "labels/val/nested/b.txt",
                "data.yaml",
                "classes.txt",
                "export_report.json",
            }
            assert archive.read("classes.txt").decode("utf-8") == "defect\nscratch\n"
            assert archive.read("labels/train/a.txt").decode("utf-8").splitlines() == [
                "0 0.250000 0.500000 0.300000 0.500000",
                "1 0.700000 0.375000 0.400000 0.500000",
            ]
            assert archive.read("labels/val/nested/b.txt").decode("utf-8").splitlines() == [
                "1 0.200000 0.250000 0.200000 0.300000",
                "0 0.650000 0.450000 0.300000 0.500000",
            ]
            data_yaml = archive.read("data.yaml").decode("utf-8")
            assert "task: detect" in data_yaml
            assert "0: defect" in data_yaml
            assert "1: scratch" in data_yaml
            report = json.loads(archive.read("export_report.json"))
            assert report["raw_images_included"] is False
            assert report["exported_sample_count"] == 2
            assert report["skipped_empty_sample_count"] == 1

    app.dependency_overrides.clear()


def test_yolo_segmentation_export_writes_polygon_vertices(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_export_dataset(client, tmp_path)
        response = export_response(
            client,
            dataset_id,
            "yolo_segmentation",
            sample_ids=[samples["a.png"]["id"]],
        )

        assert response.status_code == 200
        with ZipFile(BytesIO(response.content)) as archive:
            lines = archive.read("labels/train/a.txt").decode("utf-8").splitlines()
            assert lines[0] == "0 0.100000 0.250000 0.400000 0.250000 0.400000 0.750000 0.100000 0.750000"
            assert lines[1] == "1 0.500000 0.125000 0.900000 0.125000 0.800000 0.625000 0.500000 0.500000"
            assert "task: segment" in archive.read("data.yaml").decode("utf-8")

    app.dependency_overrides.clear()


def test_voc_export_filters_by_split_and_has_bbox_xml(tmp_path: Path):
    with make_client() as client:
        dataset_id, _ = create_export_dataset(client, tmp_path)
        response = export_response(client, dataset_id, "voc", split="train")

        assert response.status_code == 200
        with ZipFile(BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == {"annotations/a.xml", "export_report.json"}
            root = ElementTree.fromstring(archive.read("annotations/a.xml"))
            assert root.findtext("folder") == "Export Dataset"
            assert root.findtext("filename") == "a.png"
            assert root.findtext("path") == "a.png"
            assert root.findtext("size/width") == "100"
            assert root.findtext("size/height") == "80"
            objects = root.findall("object")
            assert [item.findtext("name") for item in objects] == ["defect", "scratch"]
            assert [objects[0].findtext(f"bndbox/{name}") for name in ("xmin", "ymin", "xmax", "ymax")] == [
                "10",
                "20",
                "40",
                "60",
            ]

    app.dependency_overrides.clear()


def test_real_export_is_blocked_when_selected_sample_only_has_point(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_export_dataset(client, tmp_path)
        point_only = client.put(
            f"/api/samples/{samples['a.png']['id']}/annotations",
            json={"annotations": [{"label": "dot", "shape_type": "point", "points": [5, 5]}]},
        )
        assert point_only.status_code == 200
        response = export_response(
            client,
            dataset_id,
            "yolo_detection",
            sample_ids=[samples["a.png"]["id"]],
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "ANNOTATION_EXPORT_BLOCKED"
        assert detail["precheck"]["blocked"] is True
        assert any(issue["code"] == "NO_EXPORTABLE_OBJECTS" for issue in detail["precheck"]["issues"])

    app.dependency_overrides.clear()
