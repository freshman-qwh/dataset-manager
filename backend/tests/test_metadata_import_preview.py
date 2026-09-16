from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app


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


def _create_scanned_dataset(client: TestClient, root: Path, filenames: list[str]) -> tuple[int, list[dict]]:
    for filename in filenames:
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(filename.encode("utf-8"))
    dataset = client.post(
        "/api/datasets",
        json={"name": "metadata preview", "root_path": str(root)},
    ).json()
    scanned = client.post(
        f"/api/datasets/{dataset['id']}/scan",
        json={"folder_path": str(root)},
    )
    assert scanned.status_code == 200
    samples = client.get(
        f"/api/datasets/{dataset['id']}/samples",
        params={"page_size": 200, "sort_by": "relative_path", "sort_order": "asc"},
    ).json()["items"]
    return dataset["id"], samples


def test_metadata_import_preview_is_read_only_and_fingerprint_protects_apply(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "relative_path,tags,review_status\n"
        "a.png,cat,approved\n"
        ",missing,approved\n"
        "missing.png,nope,approved\n"
        "b.png,bad,invalid\n",
        encoding="utf-8",
    )
    with _make_client() as client:
        dataset_id, samples = _create_scanned_dataset(
            client,
            tmp_path / "raw",
            ["a.png", "b.png"],
        )
        preview = client.post(
            f"/api/datasets/{dataset_id}/import-metadata",
            json={
                "file_path": str(metadata),
                "match_by": "relative_path",
                "tag_column": "tags",
                "replace_tags": False,
                "dry_run": True,
            },
        )
        assert preview.status_code == 200
        payload = preview.json()
        assert payload["dry_run"] is True
        assert payload["total_rows"] == 4
        assert payload["matched"] == 2
        assert payload["planned_updates"] == 1
        assert payload["updated"] == 0
        assert payload["skipped"] == 3
        assert payload["error_count"] == 3
        assert len(payload["source_sha256"]) == 64
        assert {issue["code"] for issue in payload["issues"]} == {
            "INVALID_REVIEW_STATUS",
            "MISSING_MATCH_VALUE",
            "SAMPLE_NOT_FOUND",
        }
        assert {issue["row_number"] for issue in payload["issues"]} == {2, 3, 4}

        unchanged = client.get(f"/api/samples/{samples[0]['id']}").json()
        assert unchanged["review_status"] == "not_reviewed"
        assert unchanged["tags"] == []

        previous_sha256 = payload["source_sha256"]
        metadata.write_text(metadata.read_text(encoding="utf-8") + "a.png,new,approved\n", encoding="utf-8")
        stale_apply = client.post(
            f"/api/datasets/{dataset_id}/import-metadata",
            json={
                "file_path": str(metadata),
                "match_by": "relative_path",
                "tag_column": "tags",
                "replace_tags": False,
                "expected_source_sha256": previous_sha256,
            },
        )
        assert stale_apply.status_code == 409
        still_unchanged = client.get(f"/api/samples/{samples[0]['id']}").json()
        assert still_unchanged["review_status"] == "not_reviewed"
        assert still_unchanged["tags"] == []

        next_preview = client.post(
            f"/api/datasets/{dataset_id}/import-metadata",
            json={"file_path": str(metadata), "dry_run": True},
        ).json()
        applied = client.post(
            f"/api/datasets/{dataset_id}/import-metadata",
            json={
                "file_path": str(metadata),
                "expected_source_sha256": next_preview["source_sha256"],
            },
        )
        assert applied.status_code == 200
        assert applied.json()["dry_run"] is False
        assert applied.json()["planned_updates"] == 2
        assert applied.json()["updated"] == 2
        changed = client.get(f"/api/samples/{samples[0]['id']}").json()
        assert changed["review_status"] == "approved"
        assert {tag["name"] for tag in changed["tags"]} == {"cat", "new"}

    app.dependency_overrides.clear()


def test_metadata_import_preview_rejects_ambiguous_filename_match(tmp_path: Path) -> None:
    metadata = tmp_path / "ambiguous.csv"
    metadata.write_text("filename,tags\na.png,ambiguous\n", encoding="utf-8")
    with _make_client() as client:
        dataset_id, samples = _create_scanned_dataset(
            client,
            tmp_path / "raw",
            ["first/a.png", "second/a.png"],
        )
        preview = client.post(
            f"/api/datasets/{dataset_id}/import-metadata",
            json={"file_path": str(metadata), "match_by": "filename", "dry_run": True},
        )
        assert preview.status_code == 200
        payload = preview.json()
        assert payload["matched"] == 0
        assert payload["planned_updates"] == 0
        assert payload["error_count"] == 1
        assert payload["issues"][0]["code"] == "AMBIGUOUS_SAMPLE_MATCH"
        assert payload["issues"][0]["row_number"] == 1
        assert all(client.get(f"/api/samples/{sample['id']}").json()["tags"] == [] for sample in samples)

    app.dependency_overrides.clear()
