from pathlib import Path

from test_dataset_api import make_client


def test_unannotated_broken_image_is_reported_before_work_starts(tmp_path: Path) -> None:
    root = tmp_path / "images"
    root.mkdir()
    (root / "broken.jpg").write_bytes(b"not an image")
    client = make_client()
    dataset = client.post("/api/datasets", json={"name": "decode", "root_path": str(root)}).json()
    client.post(f"/api/datasets/{dataset['id']}/scan", json={})
    report = client.get(f"/api/datasets/{dataset['id']}/quality-report").json()
    assert report["check_counts"]["IMAGE_UNREADABLE"] == 1
    issue = next(i for i in report["issues"] if i["code"] == "IMAGE_UNREADABLE")
    assert issue["sample_id"] and issue["sample_path"] == "broken.jpg"
