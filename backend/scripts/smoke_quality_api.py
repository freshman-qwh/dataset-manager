"""Run a raw-data-safe quality report API smoke test against an existing folder."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.utils.image_size import read_image_size  # noqa: E402


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


def _find_readable_image(client: TestClient, dataset_id: int) -> tuple[dict, tuple[int, int]]:
    page = 1
    while True:
        response = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"file_type": "image", "page": page, "page_size": 200, "sort_by": "relative_path", "sort_order": "asc"},
        )
        _require_ok(response, f"list image samples page {page}")
        payload = response.json()
        for sample in payload["items"]:
            image_size = read_image_size(Path(sample["absolute_path"]))
            if image_size and image_size[0] > 0 and image_size[1] > 0:
                return sample, image_size
        if page * payload["page_size"] >= payload["total"]:
            break
        page += 1
    raise RuntimeError("No readable image sample was found in the dataset.")


def run_smoke(dataset_root: Path) -> dict[str, object]:
    root = dataset_root.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"Dataset root is not a directory: {root}")

    client = _make_client()
    try:
        with client:
            created = client.post(
                "/api/datasets",
                json={"name": "Quality API smoke", "root_path": str(root), "task_type": "detection"},
            )
            _require_ok(created, "create in-memory dataset", expected_status=201)
            dataset_id = created.json()["id"]

            scan = client.post(f"/api/datasets/{dataset_id}/scan", json={"folder_path": str(root)})
            _require_ok(scan, "scan real dataset")
            scan_result = scan.json()

            sample, (width, height) = _find_readable_image(client, dataset_id)
            raw_path = Path(sample["absolute_path"])
            before = _file_snapshot(raw_path)

            saved = client.put(
                f"/api/samples/{sample['id']}/annotations",
                json={
                    "annotations": [
                        {
                            "label": "quality-smoke",
                            "shape_type": "rectangle",
                            "points": [0.0, 0.0, float(width), float(height)],
                            "attributes": {"occluded": True, "truncated": False, "difficult": True},
                        }
                    ],
                    "review_status": "approved",
                },
            )
            _require_ok(saved, "save in-memory annotation")

            rejected = client.put(
                f"/api/samples/{sample['id']}/annotations",
                json={"annotations": [{"label": "bad", "shape_type": "rectangle", "points": [0, 0, width + 1, height]}]},
            )
            if rejected.status_code != 400:
                raise AssertionError(f"Out-of-bounds save was not rejected: HTTP {rejected.status_code}")

            started = perf_counter()
            quality = client.get(f"/api/datasets/{dataset_id}/quality-report")
            report_seconds = perf_counter() - started
            _require_ok(quality, "build quality report")
            report = quality.json()
            if report["samples_with_objects_count"] != 1 or report["annotation_count"] != 1:
                raise AssertionError("Rejected replacement changed the previously saved annotation metadata.")
            if report["check_counts"].get("ANNOTATION_NOT_STARTED", 0) <= 0:
                raise AssertionError("Quality report did not find samples whose annotation has not started.")

            not_started = client.get(
                f"/api/datasets/{dataset_id}/samples",
                params={"file_type": "image", "annotation_progress": "not_started", "page_size": 1},
            )
            _require_ok(not_started, "filter annotation not started")
            if not_started.json()["total"] != report["image_sample_count"] - 1:
                raise AssertionError("Annotation progress filter count differs from the quality report.")

            after = _file_snapshot(raw_path)
            if after != before:
                raise AssertionError(f"Raw image changed during quality smoke test: {raw_path}")

            return {
                "dataset_root": str(root),
                "scan": {
                    "scanned": scan_result["scanned"],
                    "imported": scan_result["imported"],
                    "skipped_unsupported": scan_result["skipped_unsupported"],
                    "error_count": len(scan_result["errors"]),
                },
                "quality": {
                    "image_sample_count": report["image_sample_count"],
                    "samples_with_objects_count": report["samples_with_objects_count"],
                    "annotation_count": report["annotation_count"],
                    "issue_count": report["issue_count"],
                    "annotation_not_started_count": report["check_counts"]["ANNOTATION_NOT_STARTED"],
                    "truncated_issue_count": report["truncated_issue_count"],
                    "report_seconds": round(report_seconds, 3),
                },
                "sample": {
                    "id": sample["id"],
                    "relative_path": sample["relative_path"],
                    "sha256_unchanged": True,
                },
            }
    finally:
        app.dependency_overrides.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Existing dataset folder to scan read-only")
    args = parser.parse_args()
    print(json.dumps(run_smoke(args.root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
