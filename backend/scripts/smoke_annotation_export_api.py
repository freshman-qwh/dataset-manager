"""Run a read-only-on-raw-files API smoke test for annotation exports."""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.utils.image_size import read_image_size  # noqa: E402


EXPORT_FORMATS = (
    "labelme",
    "coco_detection",
    "coco_segmentation",
    "yolo_detection",
    "yolo_segmentation",
    "voc",
)
RAW_IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def _make_client() -> TestClient:
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


def _require_ok(response, step: str, expected_status: int = 200) -> None:
    if response.status_code != expected_status:
        raise RuntimeError(f"{step} failed: HTTP {response.status_code}: {response.text[:1000]}")


def _file_snapshot(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return stat.st_size, stat.st_mtime_ns, digest.hexdigest()


def _find_readable_image_sample(client: TestClient, dataset_id: int) -> tuple[dict, tuple[int, int]]:
    page = 1
    while True:
        response = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={
                "file_type": "image",
                "page": page,
                "page_size": 200,
                "sort_by": "relative_path",
                "sort_order": "asc",
            },
        )
        _require_ok(response, f"list image samples page {page}")
        payload = response.json()
        for sample in payload["items"]:
            size = read_image_size(Path(sample["absolute_path"]))
            if size and size[0] > 0 and size[1] > 0:
                return sample, size
        if page >= payload["pages"]:
            break
        page += 1
    raise RuntimeError("No readable PNG/JPEG/GIF/BMP image was found in the dataset.")


def _assert_archive_has_no_raw_images(content: bytes, export_format: str) -> list[str]:
    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        raw_entries = [name for name in names if Path(name).suffix.lower() in RAW_IMAGE_SUFFIXES]
        if raw_entries:
            raise AssertionError(f"{export_format} unexpectedly included raw images: {raw_entries[:5]}")
        if "export_report.json" not in names:
            raise AssertionError(f"{export_format} did not include export_report.json")
        report = json.loads(archive.read("export_report.json"))
        if report.get("raw_images_included") is not False:
            raise AssertionError(f"{export_format} report did not confirm raw_images_included=false")
        return names


def run_smoke(dataset_root: Path) -> dict[str, object]:
    root = dataset_root.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"Dataset root is not a directory: {root}")

    client = _make_client()
    try:
        with client:
            create_response = client.post(
                "/api/datasets",
                json={
                    "name": "Annotation export API smoke",
                    "root_path": str(root),
                    "task_type": "detection",
                },
            )
            _require_ok(create_response, "create in-memory dataset", expected_status=201)
            dataset_id = create_response.json()["id"]

            scan_response = client.post(
                f"/api/datasets/{dataset_id}/scan",
                json={"folder_path": str(root)},
            )
            _require_ok(scan_response, "scan real dataset")
            scan_result = scan_response.json()

            sample, (width, height) = _find_readable_image_sample(client, dataset_id)
            raw_path = Path(sample["absolute_path"])
            before = _file_snapshot(raw_path)

            patch_response = client.patch(
                f"/api/samples/{sample['id']}",
                json={"split": "train"},
            )
            _require_ok(patch_response, "assign in-memory sample split")

            replace_response = client.put(
                f"/api/samples/{sample['id']}/annotations",
                json={
                    "annotations": [
                        {
                            "label": "smoke-rectangle",
                            "shape_type": "rectangle",
                            "points": [0.0, 0.0, float(width), float(height)],
                        },
                        {
                            "label": "smoke-polygon",
                            "shape_type": "polygon",
                            "points": [
                                0.0,
                                0.0,
                                float(width),
                                0.0,
                                float(width),
                                float(height),
                                0.0,
                                float(height),
                            ],
                        },
                    ],
                    "review_status": "approved",
                },
            )
            _require_ok(replace_response, "save synthetic annotations in memory")

            exports: dict[str, object] = {}
            for export_format in EXPORT_FORMATS:
                precheck_response = client.post(
                    f"/api/datasets/{dataset_id}/annotation-export-precheck",
                    json={
                        "format": export_format,
                        "sample_query": {"sample_ids": [sample["id"]]},
                        "include_empty": False,
                    },
                )
                _require_ok(precheck_response, f"precheck {export_format}")
                precheck = precheck_response.json()
                if precheck["blocked"] or precheck["error_count"]:
                    raise AssertionError(f"{export_format} precheck was blocked: {precheck['issues']}")

                export_response = client.get(
                    f"/api/datasets/{dataset_id}/annotation-export",
                    params=[("format", export_format), ("sample_ids", sample["id"])],
                )
                _require_ok(export_response, f"export {export_format}")
                if not export_response.content:
                    raise AssertionError(f"{export_format} returned an empty body")

                if export_format.startswith("coco_"):
                    payload = export_response.json()
                    if len(payload["images"]) != 1 or len(payload["annotations"]) != 2:
                        raise AssertionError(f"{export_format} returned unexpected COCO counts")
                    artifact_entries: int | None = None
                else:
                    names = _assert_archive_has_no_raw_images(export_response.content, export_format)
                    artifact_entries = len(names)

                exports[export_format] = {
                    "status": export_response.status_code,
                    "bytes": len(export_response.content),
                    "warning_count": precheck["warning_count"],
                    "artifact_entries": artifact_entries,
                }

            after = _file_snapshot(raw_path)
            if after != before:
                raise AssertionError(f"Raw image changed during export smoke test: {raw_path}")

            return {
                "dataset_root": str(root),
                "scan": {
                    "scanned": scan_result["scanned"],
                    "imported": scan_result["imported"],
                    "skipped_unsupported": scan_result["skipped_unsupported"],
                    "error_count": len(scan_result["errors"]),
                },
                "sample": {
                    "id": sample["id"],
                    "relative_path": sample["relative_path"],
                    "width": width,
                    "height": height,
                    "sha256_unchanged": True,
                },
                "exports": exports,
            }
    finally:
        app.dependency_overrides.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Existing dataset folder to scan read-only")
    args = parser.parse_args()
    result = run_smoke(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
