from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models.dataset import Dataset
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample


@pytest.fixture
def card_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Dataset card", description="Collection overview", triage_policy_version=2)
        other = Dataset(name="Private collection")
        session.add_all([dataset, other]); session.commit()
        ids = dataset.id, other.id
    def override():
        with Session(engine) as session:
            yield session
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = override
    try:
        yield TestClient(app), engine, ids
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def sample(dataset_id, index, **values):
    return Sample(dataset_id=dataset_id, filename=f"part-{index}.png",
        absolute_path=f"/offline/{dataset_id}/part-{index}.png", relative_path=f"part-{index}.png",
        file_type="image", extension=".png", file_hash=f"{index:064x}", **values)


def test_dataset_card_handles_empty_nonimages_and_unknown_dataset(card_client):
    client, engine, (dataset_id, _) = card_client
    empty = client.get(f"/api/datasets/{dataset_id}/card")
    assert empty.status_code == 200, empty.text
    value = empty.json()
    assert value["dataset"]["name"] == "Dataset card"
    assert value["summary"]["sample_count"] == value["summary"]["image_count"] == 0
    assert value["preview_samples"] == value["categories"] == []
    assert value["generated_at"]
    assert client.get("/api/datasets/99999/card").status_code == 404
    with Session(engine) as session:
        session.add(Sample(dataset_id=dataset_id, filename="table.csv", absolute_path="/offline/table.csv",
            relative_path="table.csv", extension=".csv", file_type="csv", file_hash="table", file_status="missing", split="train"))
        session.commit()
    nonimage = client.get(f"/api/datasets/{dataset_id}/card").json()
    assert nonimage["summary"]["sample_count"] == nonimage["summary"]["unavailable_count"] == 1
    assert nonimage["summary"]["image_count"] == nonimage["summary"]["normal_count"] == 0
    assert sum(nonimage["summary"]["splits"].values()) == 0
    assert nonimage["preview_samples"] == []


def test_card_counts_entire_dataset_and_preserves_label_precedence(card_client):
    client, engine, (dataset_id, other_id) = card_client
    with Session(engine) as session:
        for index in range(130):
            session.add(sample(dataset_id, index, benchmark_label="normal", split="train"))
        session.add(sample(dataset_id, 130, triage_status="ng", triaged_file_hash=f"{130:064x}", triage_policy_version=2, benchmark_label="normal", split="test", mask_path="/offline/mask.png"))
        session.add(sample(dataset_id, 131, triage_status="pending", benchmark_label="normal"))
        session.add(sample(dataset_id, 132, triage_status="ok", triaged_file_hash="old-content", triage_policy_version=2, benchmark_label="anomaly"))
        session.add(sample(dataset_id, 133, triage_status="ng", triaged_file_hash=f"{133:064x}", triage_policy_version=1, benchmark_label="anomaly"))
        session.add(sample(dataset_id, 134, triage_status="ok", triaged_file_hash=f"{134:064x}", triage_policy_version=2, split="val"))
        session.add(sample(dataset_id, 135, split="custom", file_status="missing"))
        session.add(sample(dataset_id, 136, benchmark_label="anomaly", file_status="permission_denied", mask_path="/offline/missing-mask.png"))
        session.add(sample(other_id, 200, benchmark_label="anomaly", mask_path="/private/mask.png"))
        session.commit()
    value = client.get(f"/api/datasets/{dataset_id}/card").json()
    summary = value["summary"]
    assert summary["sample_count"] == summary["image_count"] == 137
    assert summary["normal_count"] == 131
    assert summary["anomaly_count"] == 2
    assert summary["pending_count"] == 3
    assert summary["untriaged_count"] == 1
    assert summary["unavailable_count"] == summary["mask_count"] == 2
    assert summary["splits"] == {"train": 130, "val": 1, "test": 1, "unassigned": 5}
    assert len(value["preview_samples"]) <= 8
    assert all(item["filename"] != "part-200.png" for item in value["preview_samples"])


def test_card_category_totals_are_full_and_previews_are_bounded_and_distinct(card_client):
    client, engine, (dataset_id, _) = card_client
    with Session(engine) as session:
        categories = [DatasetCategory(dataset_id=dataset_id, name=f"category-{index:02d}") for index in range(15)]
        session.add_all(categories)
        session.add_all([DatasetBatch(dataset_id=dataset_id, name="first"), DatasetBatch(dataset_id=dataset_id, name="second")])
        session.flush()
        for index, category in enumerate(categories):
            session.add(sample(dataset_id, index + 1, category_id=category.id, benchmark_label="normal"))
        session.commit()
    loaded_samples = []
    def on_load(value, context):
        loaded_samples.append(value.id)
    event.listen(Sample, "load", on_load)
    try:
        value = client.get(f"/api/datasets/{dataset_id}/card").json()
    finally:
        event.remove(Sample, "load", on_load)
    assert value["summary"]["category_count"] == 15
    assert value["summary"]["batch_count"] == 2
    assert len(value["categories"]) == 12
    assert all(category["sample_count"] == category["normal_count"] == 1 for category in value["categories"])
    assert len(value["preview_samples"]) == 8
    assert len({item["category_name"] for item in value["preview_samples"]}) == 8
    assert loaded_samples == []


def test_card_deduplicates_preview_content_and_includes_normal_anomaly_examples(card_client):
    client, engine, (dataset_id, _) = card_client
    with Session(engine) as session:
        for index in range(12):
            session.add(sample(dataset_id, index, benchmark_label="normal"))
        duplicate = sample(dataset_id, 30, benchmark_label="anomaly")
        duplicate.file_hash = f"{0:064x}"
        session.add(duplicate)
        session.add(sample(dataset_id, 31, benchmark_label="anomaly"))
        session.add(sample(dataset_id, 32, benchmark_label="anomaly", file_status="missing"))
        session.commit()
    preview = client.get(f"/api/datasets/{dataset_id}/card").json()["preview_samples"]
    assert len(preview) == 8
    assert len({item["file_hash"] for item in preview}) == 8
    assert {item["label"] for item in preview} == {"normal", "anomaly"}
    assert all(item["filename"] != "part-32.png" for item in preview)


def test_card_is_metadata_only_and_never_decodes_or_changes_originals(card_client, monkeypatch):
    client, engine, (dataset_id, _) = card_client
    with Session(engine) as session:
        session.add(sample(dataset_id, 1, benchmark_label="normal")); session.commit()
        before = [(item.id, item.updated_at, item.file_hash, item.triage_status) for item in session.exec(select(Sample)).all()]
        revision = session.get(Dataset, dataset_id).revision
    def no_disk(*args, **kwargs):
        raise AssertionError("Dataset cards must use metadata without reading raw files")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", no_disk)
        patch.setattr(Path, "read_bytes", no_disk)
        response = client.get(f"/api/datasets/{dataset_id}/card")
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        after = [(item.id, item.updated_at, item.file_hash, item.triage_status) for item in session.exec(select(Sample)).all()]
        assert after == before
        assert session.get(Dataset, dataset_id).revision == revision
