from pathlib import Path
import base64
import json
from zipfile import ZipFile

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


def create_image_dataset(client: TestClient, tmp_path: Path, filenames: list[str]) -> tuple[int, list[dict]]:
    data_root = tmp_path / "labelme-images"
    data_root.mkdir()
    for filename in filenames:
        path = data_root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG_1X1)

    dataset = client.post("/api/datasets", json={"name": "Labelme Images", "root_path": str(data_root)}).json()
    scan = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(data_root)})
    assert scan.status_code == 200
    samples = client.get(
        f"/api/datasets/{dataset['id']}/samples",
        params={"sort_by": "relative_path", "sort_order": "asc", "page_size": 200},
    ).json()["items"]
    return dataset["id"], samples


def write_labelme_json(path: Path, image_path: str, shapes: list[dict], image_size: tuple[int, int] = (1, 1)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "5.0.0",
                "flags": {},
                "shapes": shapes,
                "imagePath": image_path,
                "imageData": None,
                "imageWidth": image_size[0],
                "imageHeight": image_size[1],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_manual_image_match_preview_and_confirmation(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_image_dataset(client, tmp_path, ["a.png", "b.png"])
        first_id, second_id = samples[0]["id"], samples[1]["id"]
        source = tmp_path / "unmatched.json"
        write_labelme_json(source, "old-name.png", [{"label": "defect", "shape_type": "rectangle", "points": [[0, 0], [1, 1]]}])
        original = source.read_bytes()
        endpoint = f"/api/datasets/{dataset_id}/annotations/import"
        base = {"format": "labelme", "path": str(source), "mode": "file"}
        automatic = client.post(endpoint, json={**base, "dry_run": True}).json()
        assert automatic["imported_samples"] == 0
        assert automatic["matched_sample"] is None

        preview = client.post(endpoint, json={**base, "sample_id": first_id, "dry_run": True}).json()
        assert preview["matched_sample"] == {"id": first_id, "relative_path": "a.png"}
        assert client.get(f"/api/samples/{first_id}/annotations").json() == []
        confirmation = {**base, "expected_source_sha256": preview["source_sha256"], "expected_plan_fingerprint": preview["plan_fingerprint"]}
        changed_target = client.post(endpoint, json={**confirmation, "sample_id": second_id})
        assert changed_target.status_code == 409
        assert client.get(f"/api/samples/{second_id}/annotations").json() == []
        assert client.post(endpoint, json={**confirmation, "sample_id": first_id}).status_code == 200
        assert len(client.get(f"/api/samples/{first_id}/annotations").json()) == 1
        assert source.read_bytes() == original

        other_root = tmp_path / "other"
        other_root.mkdir()
        other_dataset, _ = create_image_dataset(client, other_root, ["a.png"])
        rejected = client.post(f"/api/datasets/{other_dataset}/annotations/import", json={**base, "sample_id": first_id, "dry_run": True}).json()
        assert rejected["matched_sample"] is None
        assert rejected["errors"][0]["code"] == "SAMPLE_NOT_FOUND"
    app.dependency_overrides.clear()


def test_labelme_import_dry_run_then_replace_and_export_shapes(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_image_dataset(client, tmp_path, ["sample.png"])
        sample_id = samples[0]["id"]
        labelme_file = tmp_path / "sample.json"
        write_labelme_json(
            labelme_file,
            "sample.png",
            [
                {
                    "label": "rect",
                    "shape_type": "rectangle",
                    "points": [[1, 1], [0, 0]],
                    "flags": {"ok": True, "occluded": True, "truncated": False, "difficult": True},
                },
                {"label": "poly", "shape_type": "polygon", "points": [[0, 0], [1, 0], [1, 1]], "description": "corner"},
                {"label": "dot", "shape_type": "point", "points": [[0, 0]]},
                {"label": "multi", "shape_type": "points", "points": [[0, 0], [1, 1]]},
            ],
        )

        dry_run = client.post(
            f"/api/datasets/{dataset_id}/annotations/import-labelme",
            json={"path": str(labelme_file), "mode": "file", "sample_id": sample_id, "dry_run": True},
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["created_annotations"] == 4
        assert client.get(f"/api/samples/{sample_id}/annotations").json() == []

        changed_plan = client.post(
            f"/api/datasets/{dataset_id}/annotations/import-labelme",
            json={
                "path": str(labelme_file),
                "mode": "file",
                "sample_id": sample_id,
                "dry_run": False,
                "expected_source_sha256": dry_run.json()["source_sha256"],
                "expected_plan_fingerprint": "0" * 64,
            },
        )
        assert changed_plan.status_code == 409
        assert client.get(f"/api/samples/{sample_id}/annotations").json() == []

        imported = client.post(
            f"/api/datasets/{dataset_id}/annotations/import-labelme",
            json={
                "path": str(labelme_file),
                "mode": "file",
                "sample_id": sample_id,
                "strategy": "replace",
                "expected_source_sha256": dry_run.json()["source_sha256"],
                "expected_plan_fingerprint": dry_run.json()["plan_fingerprint"],
            },
        )
        assert imported.status_code == 200
        payload = imported.json()
        assert payload["matched_files"] == 1
        assert payload["imported_samples"] == 1
        assert payload["created_annotations"] == 4
        assert payload["errors"] == []

        annotations = client.get(f"/api/samples/{sample_id}/annotations").json()
        assert [item["shape_type"] for item in annotations] == ["rectangle", "polygon", "point", "points"]
        assert annotations[0]["points"] == [0.0, 0.0, 1.0, 1.0]
        assert annotations[0]["attributes"] == {"occluded": True, "truncated": False, "difficult": True}
        assert annotations[1]["notes"] == "corner"
        assert client.get(f"/api/samples/{sample_id}").json()["tags"] == []
        classes = client.get(f"/api/datasets/{dataset_id}/annotation-classes").json()
        assert {item["name"] for item in classes} == {"rect", "poly", "dot", "multi"}
        synced = client.post(f"/api/samples/{sample_id}/annotations/sync-sample-tags")
        assert synced.status_code == 200
        assert set(synced.json()["added_tags"]) == {"rect", "poly", "dot", "multi"}

        exported = client.post(f"/api/samples/{sample_id}/annotations/export-labelme")
        assert exported.status_code == 200
        shapes = exported.json()["shapes"]
        assert shapes[0]["points"] == [[0.0, 0.0], [1.0, 1.0]]
        assert shapes[0]["flags"] == {
            "ok": True,
            "occluded": True,
            "truncated": False,
            "difficult": True,
        }
        assert shapes[1]["points"] == [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
        assert shapes[2]["points"] == [[0.0, 0.0]]
        assert shapes[3]["points"] == [[0.0, 0.0], [1.0, 1.0]]
        assert exported.json()["imageWidth"] == 1
        assert exported.json()["imageHeight"] == 1

    app.dependency_overrides.clear()


def test_labelme_directory_import_matches_relative_paths_and_skips_unknown_shapes(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_image_dataset(client, tmp_path, ["a.png", "nested/b.png"])
        import_root = tmp_path / "labelme-json"
        write_labelme_json(
            import_root / "a.json",
            "a.png",
            [
                {"label": "a-rect", "shape_type": "rectangle", "points": [[0, 0], [1, 1]]},
                {"label": "circle", "shape_type": "circle", "points": [[0, 0], [1, 1]]},
            ],
        )
        write_labelme_json(
            import_root / "nested" / "b.json",
            "nested/b.png",
            [{"label": "b-poly", "shape_type": "polygon", "points": [[0, 0], [1, 0], [1, 1]]}],
            image_size=(2, 2),
        )

        imported = client.post(
            f"/api/datasets/{dataset_id}/annotations/import-labelme",
            json={"path": str(import_root), "mode": "directory", "strategy": "replace"},
        )
        assert imported.status_code == 200
        payload = imported.json()
        assert payload["checked_files"] == 2
        assert payload["matched_files"] == 2
        assert payload["imported_samples"] == 2
        assert payload["created_annotations"] == 2
        assert payload["skipped_shapes"] == 1
        warning_codes = {item["code"] for item in payload["warnings"]}
        assert "UNSUPPORTED_SHAPE_SKIPPED" in warning_codes
        assert "IMAGE_SIZE_MISMATCH" in warning_codes

        first_annotations = client.get(f"/api/samples/{samples[0]['id']}/annotations").json()
        second_annotations = client.get(f"/api/samples/{samples[1]['id']}/annotations").json()
        assert [item["label"] for item in first_annotations] == ["a-rect"]
        assert [item["label"] for item in second_annotations] == ["b-poly"]

    app.dependency_overrides.clear()


def test_labelme_import_append_preserves_existing_annotations(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_image_dataset(client, tmp_path, ["sample.png"])
        sample_id = samples[0]["id"]
        saved = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [{"label": "old", "shape_type": "point", "points": [0, 0]}]},
        )
        assert saved.status_code == 200

        labelme_file = tmp_path / "append.json"
        write_labelme_json(
            labelme_file,
            "sample.png",
            [{"label": "new", "shape_type": "rectangle", "points": [[0, 0], [1, 1]]}],
        )
        imported = client.post(
            f"/api/datasets/{dataset_id}/annotations/import-labelme",
            json={"path": str(labelme_file), "mode": "file", "sample_id": sample_id, "strategy": "append"},
        )
        assert imported.status_code == 200
        annotations = client.get(f"/api/samples/{sample_id}/annotations").json()
        assert [item["label"] for item in annotations] == ["old", "new"]
        assert annotations[1]["z_order"] == 1

    app.dependency_overrides.clear()


def test_labelme_dataset_zip_export_includes_json_and_report(tmp_path: Path):
    with make_client() as client:
        dataset_id, samples = create_image_dataset(client, tmp_path, ["sample.png", "empty.png"])
        sample_id = next(sample["id"] for sample in samples if sample["relative_path"] == "sample.png")
        saved = client.put(
            f"/api/samples/{sample_id}/annotations",
            json={"annotations": [{"label": "rect", "shape_type": "rectangle", "points": [0, 0, 1, 1]}]},
        )
        assert saved.status_code == 200

        exported = client.get(f"/api/datasets/{dataset_id}/annotation-export", params={"format": "labelme"})
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        archive_path = tmp_path / "labelme.zip"
        archive_path.write_bytes(exported.content)

        with ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            assert "annotations/sample.json" in names
            assert "annotations/empty.json" not in names
            assert "export_report.json" in names
            payload = json.loads(archive.read("annotations/sample.json"))
            report = json.loads(archive.read("export_report.json"))

        assert payload["imagePath"] == "sample.png"
        assert payload["shapes"][0]["label"] == "rect"
        assert report["exported_files"] == 1
        assert report["skipped_empty_samples"] == 1

    app.dependency_overrides.clear()
