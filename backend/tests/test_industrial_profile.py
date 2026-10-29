from pathlib import Path

from test_dataset_api import make_client


def test_industrial_profile_does_not_require_geometry_or_tags(tmp_path: Path) -> None:
    client = make_client()
    industrial = client.post("/api/datasets", json={"name": "industrial", "workflow_profile": "industrial_anomaly"}).json()
    assert industrial["workflow_profile"] == "industrial_anomaly"
    assert industrial["task_type"] == "classification"
    assert client.get(f"/api/datasets/{industrial['id']}/triage-policy").json()["split_ok"]
    general = client.post("/api/datasets", json={"name": "existing mode"}).json()
    assert general["workflow_profile"] == "general"
    assert general["task_type"] == "detection"
    # Changing intent does not rewrite the existing policy or annotation type.
    changed = client.patch(f"/api/datasets/{general['id']}", json={"workflow_profile": "industrial_anomaly"}).json()
    assert changed["task_type"] == "detection"
    assert not client.get(f"/api/datasets/{general['id']}/triage-policy").json()["split_ok"]
    assert client.patch(f"/api/datasets/{general['id']}", json={"workflow_profile": None}).status_code == 422
    view = client.post(f"/api/datasets/{industrial['id']}/saved-views", json={
        "name": "NG review", "sample_query": {"triage_status": "ng", "triage_outdated": False},
    }).json()
    restored = client.get(f"/api/datasets/{industrial['id']}/saved-views/{view['id']}").json()
    assert restored["sample_query"]["triage_status"] == "ng"
    assert restored["sample_query"]["triage_outdated"] is False


def test_synthetic_example_is_repeatable_and_quality_uses_triage(tmp_path: Path, monkeypatch) -> None:
    from app.services import industrial_example_service
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"storage_root": tmp_path})
    monkeypatch.setattr(industrial_example_service, "get_settings", lambda: settings)
    client = make_client()
    response = client.post("/api/datasets/industrial-example")
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset["sample_count"] == 16
    assert client.post("/api/datasets/industrial-example").json()["id"] == dataset["id"]
    report = client.get(f"/api/datasets/{dataset['id']}/quality-report").json()
    assert "SAMPLE_TAG_MISSING" not in report["check_counts"]
    assert "ANNOTATION_NOT_STARTED" not in report["check_counts"]
    assert report["check_counts"].get("IMAGE_UNREADABLE", 0) == 0
