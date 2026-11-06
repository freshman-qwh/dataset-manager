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
def comparison_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Comparison", triage_policy_version=2)
        other = Dataset(name="Private comparison")
        unclassified = Dataset(name="No category")
        empty = Dataset(name="Empty")
        session.add_all([dataset, other, unclassified, empty]); session.flush()
        categories = [DatasetCategory(dataset_id=dataset.id, name=name) for name in ("A", "B", "Empty")]
        foreign_category = DatasetCategory(dataset_id=other.id, name="A")
        first = DatasetBatch(dataset_id=dataset.id, name="First")
        second = DatasetBatch(dataset_id=dataset.id, name="Second")
        foreign_batch = DatasetBatch(dataset_id=other.id, name="First")
        session.add_all([*categories, foreign_category, first, second, foreign_batch]); session.flush()
        ids = dict(dataset=dataset.id, other=other.id, unclassified=unclassified.id, empty=empty.id,
            first=first.id, second=second.id, a=categories[0].id, b=categories[1].id,
            empty_category=categories[2].id, foreign_category=foreign_category.id, foreign_batch=foreign_batch.id)
        index = 0
        def add(*, dataset_id=dataset.id, category_id=categories[0].id, batch_id=first.id,
                label=None, triage="untriaged", current=True, filename=None, source="first", **extra):
            nonlocal index
            index += 1
            filename = filename or f"part-{index:02d}.png"
            digest = f"{index:064x}"
            values = dict(dataset_id=dataset_id, filename=filename,
                relative_path="nested/"+filename, absolute_path=f"/{source}/nested/{filename}",
                category_id=category_id, batch_id=batch_id, extension=".png", file_type="image",
                file_hash=digest, benchmark_label=label, triage_status=triage)
            if triage in {"ok", "ng"}:
                values.update(triaged_file_hash=digest if current else "previous-content", triage_policy_version=2)
            values.update(extra)
            session.add(Sample(**values))
        add(label="normal", filename="same.png")
        add(triage="ok", ok_grade="clear")
        add(triage="ok", ok_grade="borderline")
        add(triage="ng", label="normal", mask_path="/mask.png")
        add(triage="pending", label="normal")
        add(triage="ok", current=False, label="normal")
        add(triage="ng", triage_policy_version=1, label="anomaly")
        add()
        add(label="normal", file_status="missing")
        add(label="anomaly", file_status="permission_denied")
        add(file_type="csv", extension=".csv", filename="metadata.csv", label="normal")
        # Same folder/filename in a different source remains a separate sample.
        add(label="normal", filename="same.png", source="second", batch_id=second.id)
        add(category_id=categories[1].id, label="normal")
        add(category_id=categories[1].id, label="anomaly")
        add(category_id=categories[1].id, batch_id=second.id, label="normal")
        add(category_id=categories[1].id, batch_id=second.id, label="anomaly")
        add(category_id=None, label="normal")
        add(category_id=None, label="anomaly")
        add(dataset_id=other.id, category_id=foreign_category.id, batch_id=foreign_batch.id, label="normal")
        add(dataset_id=unclassified.id, category_id=None, batch_id=None, label="normal", source="unclassified")
        add(dataset_id=unclassified.id, category_id=None, batch_id=None, label="anomaly", source="unclassified")
        session.commit()
    def override():
        with Session(engine) as session:
            yield session
    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = override
    try:
        yield TestClient(app), engine, ids
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(old)
        engine.dispose()


def test_default_comparison_stays_in_one_category_across_sources(comparison_client):
    client, _, ids = comparison_client
    response = client.get(f"/api/datasets/{ids['dataset']}/comparison")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["category_id"] == ids["a"] and value["batch_id"] is None
    assert value["normal"]["total"] == 4
    assert value["anomaly"]["total"] == 1
    assert value["excluded_count"] == 6
    assert all(item["category_id"] == ids["a"] for side in ("normal", "anomaly") for item in value[side]["items"])
    same_named = [item for item in value["normal"]["items"] if item["filename"] == "same.png"]
    assert len(same_named) == 2 and len({item["absolute_path"] for item in same_named}) == 2
    assert any(item["ok_grade"] == "borderline" for item in value["normal"]["items"])


def test_comparison_respects_current_truth_pending_and_stale_exclusions(comparison_client):
    client, _, ids = comparison_client
    value = client.get(f"/api/datasets/{ids['dataset']}/comparison", params={"category_id": ids['a'], "batch_id": ids['first']}).json()
    assert value["normal"]["total"] == 3 and value["anomaly"]["total"] == 1
    assert value["excluded_count"] == 6
    assert value["anomaly"]["items"][0]["triage_status"] == "ng"
    assert value["anomaly"]["items"][0]["benchmark_label"] == "normal"
    assert value["anomaly"]["items"][0]["mask_path"] == "/mask.png"
    assert all(item["file_status"] == "normal" and not item["triage_outdated"] for side in ("normal", "anomaly") for item in value[side]["items"])


def test_comparison_category_batch_isolation_and_empty_categories(comparison_client):
    client, _, ids = comparison_client
    value = client.get(f"/api/datasets/{ids['dataset']}/comparison", params={"category_id": ids['b'], "batch_id": ids['second']}).json()
    assert value["normal"]["total"] == value["anomaly"]["total"] == 1
    assert value["excluded_count"] == 0
    assert all(item["category_id"] == ids['b'] and item["batch_id"] == ids['second'] for side in ("normal", "anomaly") for item in value[side]["items"])
    empty = client.get(f"/api/datasets/{ids['dataset']}/comparison", params={"category_id": ids['empty_category']}).json()
    assert empty["category_id"] == ids['empty_category']
    assert empty["normal"]["items"] == empty["anomaly"]["items"] == []
    assert empty["excluded_count"] == 0
    for params in ({"category_id": ids['foreign_category']}, {"batch_id": ids['foreign_batch']}):
        assert client.get(f"/api/datasets/{ids['dataset']}/comparison", params=params).status_code == 422


def test_comparison_independent_pagination_clamps_and_keeps_orm_loads_bounded(comparison_client):
    client, engine, ids = comparison_client
    loaded = []
    def on_load(value, context):
        loaded.append(value.id)
    event.listen(Sample, "load", on_load)
    try:
        value = client.get(f"/api/datasets/{ids['dataset']}/comparison", params={"page_size": 2, "normal_page": 999, "anomaly_page": 999}).json()
    finally:
        event.remove(Sample, "load", on_load)
    assert value["normal"]["page"] == 2 and len(value["normal"]["items"]) == 2
    assert value["anomaly"]["page"] == 1 and len(value["anomaly"]["items"]) == 1
    assert len(loaded) == 3
    for params in ({"page_size": 25}, {"page_size": 0}, {"normal_page": 0}, {"anomaly_page": 0}, {"category_id": 0}):
        assert client.get(f"/api/datasets/{ids['dataset']}/comparison", params=params).status_code == 422


def test_comparison_works_without_categories_and_handles_unknown_dataset(comparison_client):
    client, _, ids = comparison_client
    value = client.get(f"/api/datasets/{ids['unclassified']}/comparison").json()
    assert value["category_id"] is None
    assert value["normal"]["total"] == value["anomaly"]["total"] == 1
    empty = client.get(f"/api/datasets/{ids['empty']}/comparison").json()
    assert empty["category_id"] is None and empty["normal"]["total"] == empty["anomaly"]["total"] == 0
    assert client.get("/api/datasets/99999/comparison").status_code == 404


def test_default_category_comes_from_selected_batch_and_skips_empty_records(comparison_client):
    client, engine, ids = comparison_client
    with Session(engine) as session:
        batch = DatasetBatch(dataset_id=ids['dataset'], name="Only B")
        session.add(batch)
        session.add(DatasetCategory(dataset_id=ids['dataset'], name="0-empty-first"))
        session.flush()
        batch_id = batch.id
        session.add(Sample(dataset_id=ids['dataset'], filename="batch-only.png",
            relative_path="batch-only.png", absolute_path="/third/batch-only.png", extension=".png",
            file_type="image", file_hash="d"*64, category_id=ids['b'], batch_id=batch_id, benchmark_label="normal"))
        session.commit()
    value = client.get(f"/api/datasets/{ids['dataset']}/comparison", params={"batch_id": batch_id}).json()
    assert value["category_id"] == ids['b']
    assert value["normal"]["total"] == 1 and value["anomaly"]["total"] == 0


def test_comparison_never_reads_disk_or_changes_metadata(comparison_client, monkeypatch):
    client, engine, ids = comparison_client
    with Session(engine) as session:
        before = [(row.id, row.category_id, row.batch_id, row.triage_status, row.file_hash, row.updated_at) for row in session.exec(select(Sample)).all()]
        revision = session.get(Dataset, ids['dataset']).revision
    def no_disk(*args, **kwargs):
        raise AssertionError("Comparison must use registered metadata only")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", no_disk); patch.setattr(Path, "iterdir", no_disk)
        result = client.get(f"/api/datasets/{ids['dataset']}/comparison")
    assert result.status_code == 200, result.text
    with Session(engine) as session:
        after = [(row.id, row.category_id, row.batch_id, row.triage_status, row.file_hash, row.updated_at) for row in session.exec(select(Sample)).all()]
        assert after == before and session.get(Dataset, ids['dataset']).revision == revision
