from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.daily_tools import router
from app.core.database import get_session
from app.models.dataset import Dataset
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample


@pytest.fixture
def daily_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Daily", triage_policy_version=2)
        foreign = Dataset(name="Foreign")
        empty = Dataset(name="Empty")
        session.add_all([dataset, foreign, empty]); session.flush()
        category = DatasetCategory(dataset_id=dataset.id, name="Part")
        unused = DatasetCategory(dataset_id=dataset.id, name="Unused category")
        batch = DatasetBatch(dataset_id=dataset.id, name="First")
        foreign_category = DatasetCategory(dataset_id=foreign.id, name="Other")
        session.add_all([category, unused, batch, foreign_category]); session.flush()
        ids = dict(dataset=dataset.id, foreign=foreign.id, empty=empty.id, category=category.id,
            batch=batch.id, unused=unused.id, foreign_category=foreign_category.id)
        index = 0

        def add(filename, *, directory="C:/images", category_id=category.id, batch_id=batch.id, **extra):
            nonlocal index
            index += 1
            digest = f"{index:064x}"
            fields = dict(dataset_id=dataset.id, category_id=category_id, batch_id=batch_id,
                filename=filename, relative_path="nested/" + filename,
                absolute_path=directory + "/nested/" + filename, extension=".png", file_type="image", file_hash=digest)
            fields.update(extra)
            session.add(Sample(**fields))

        add("same.png", benchmark_label="normal")
        add("same.png", directory="D:/another", benchmark_label="anomaly")
        add("clear.png", triage_status="ok", triaged_file_hash=f"{3:064x}", triage_policy_version=2)
        add("pending.png", triage_status="pending", benchmark_label="normal")
        add("stale.png", triage_status="ng", triaged_file_hash="old", triage_policy_version=2, benchmark_label="anomaly")
        add("policy.png", triage_status="ok", triaged_file_hash=f"{6:064x}", triage_policy_version=1)
        add("unknown.png")
        add("missing.png", file_status="missing", benchmark_label="normal")
        add("unassigned.png", category_id=None, batch_id=None, benchmark_label="normal")
        add("Case.PNG", directory="/posix")
        add("literal%_.png", category_id=None, batch_id=batch.id)
        add("data.csv", file_type="csv", extension=".csv")
        add("secret.png", dataset_id=foreign.id, category_id=foreign_category.id, batch_id=None)
        for number in range(8):
            add("many.png", directory=f"E:/batch-{number}")
        session.commit()
    api = FastAPI()
    api.include_router(router)

    def override():
        with Session(engine) as session:
            yield session
    api.dependency_overrides[get_session] = override
    try:
        yield TestClient(api), engine, ids
    finally:
        engine.dispose()


def test_lookup_reports_ambiguity_exact_paths_and_missing(daily_client):
    client, _, ids = daily_client
    response = client.post(f"/api/datasets/{ids['dataset']}/filename-lookup", json={"entries": [
        "same.png", "nested\\same.png", '"c:\\IMAGES\\nested\\SAME.PNG"', "absent.png", "secret.png", "data.csv"]})
    assert response.status_code == 200, response.text
    rows = response.json()["results"]
    assert [row["total"] for row in rows] == [2, 2, 1, 0, 0, 0]
    assert rows[2]["candidates"][0]["absolute_path"] == "C:/images/nested/same.png"
    assert len({item["id"] for item in rows[0]["candidates"]}) == 2


def test_lookup_duplicates_blanks_literals_and_posix_case(daily_client):
    client, _, ids = daily_client
    value = client.post(f"/api/datasets/{ids['dataset']}/filename-lookup", json={"entries": [
        " same.png ", '"same.png"', "nested\\same.png", "nested/same.png", "", "literal%_.png", "%", "case.png", "Case.PNG"]}).json()
    assert value["duplicate_count"] == 2 and value["blank_count"] == 1
    assert [row["total"] for row in value["results"]] == [2, 2, 1, 0, 0, 1]


def test_candidate_pages_bound_loads_and_keep_all_ambiguous_choices(daily_client):
    client, _, ids = daily_client
    root = f"/api/datasets/{ids['dataset']}/filename-lookup"
    row = client.post(root, json={"entries": ["many.png"]}).json()["results"][0]
    assert row["total"] == 8 and len(row["candidates"]) == 5
    page = client.get(root + "/candidates", params={"entry": "many.png", "page": 2}).json()
    assert page["page"] == 2 and len(page["candidates"]) == 3
    assert len({item["id"] for item in row["candidates"] + page["candidates"]}) == 8
    assert client.get(root + "/candidates", params={"entry": "many.png", "page": 99}).json()["page"] == 2


def test_lookup_validation_and_unknown_dataset(daily_client):
    client, _, ids = daily_client
    root = f"/api/datasets/{ids['dataset']}/filename-lookup"
    for entries in ([], ["x"] * 501, ["x" * 2001]):
        assert client.post(root, json={"entries": entries}).status_code == 422
    for params in ({"entry": "many.png", "page": 0}, {"entry": "many.png", "page_size": 21}, {"entry": ""}):
        assert client.get(root + "/candidates", params=params).status_code == 422
    assert client.post("/api/datasets/99999/filename-lookup", json={"entries": ["x"]}).status_code == 404


def test_coverage_uses_current_effective_truth_and_partitions_every_image(daily_client):
    client, _, ids = daily_client
    response = client.get(f"/api/datasets/{ids['dataset']}/coverage")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["totals"] == dict(total=19, normal=3, anomaly=1, pending=1, stale=2, untriaged=11, unavailable=1)
    assert sum(data["totals"][key] for key in ("normal", "anomaly", "pending", "stale", "untriaged", "unavailable")) == data["totals"]["total"]
    assert any(axis["id"] == ids["unused"] for axis in data["categories"])
    assert data["categories"][-1]["id"] is None and data["batches"][-1]["id"] is None
    unassigned = next(row for row in data["cells"] if row["category_id"] is None and row["batch_id"] is None)
    assert unassigned["normal"] == 1
    assert all(row["category_id"] != ids["foreign_category"] for row in data["cells"])


def test_cell_samples_match_each_counter_and_do_not_treat_null_as_all(daily_client):
    client, _, ids = daily_client
    root = f"/api/datasets/{ids['dataset']}/coverage"
    coverage = client.get(root).json()
    for cell in coverage["cells"]:
        scope = {key: cell[key] for key in ("category_id", "batch_id") if cell[key] is not None}
        for status in ("normal", "anomaly", "pending", "stale", "untriaged", "unavailable"):
            result = client.get(root + "/samples", params={**scope, "status": status}).json()
            assert result["total"] == cell[status], (cell, status, result)
            assert all(item["category_id"] == cell["category_id"] and item["batch_id"] == cell["batch_id"] for item in result["items"])
    unassigned = client.get(root + "/samples").json()
    assert unassigned["total"] == 1 and unassigned["items"][0]["filename"] == "unassigned.png"


def test_cell_pagination_validation_empty_and_unknown(daily_client):
    client, _, ids = daily_client
    root = f"/api/datasets/{ids['dataset']}/coverage"
    scope = {"category_id": ids["category"], "batch_id": ids["batch"], "status": "untriaged", "page_size": 3, "page": 99}
    data = client.get(root + "/samples", params=scope).json()
    assert data["page"] == 4 and len(data["items"]) == 1 and data["total"] == 10
    for params in ({"category_id": ids["foreign_category"]}, {"status": "invalid"}, {"page": 0}, {"page_size": 25}, {"category_id": 0}):
        assert client.get(root + "/samples", params=params).status_code == 422
    empty = client.get(f"/api/datasets/{ids['empty']}/coverage").json()
    assert empty["totals"]["total"] == 0 and empty["cells"] == []
    assert client.get("/api/datasets/99999/coverage").status_code == 404


def test_helpers_are_metadata_only_and_bound_orm_sample_loads(daily_client, monkeypatch):
    client, engine, ids = daily_client
    with Session(engine) as session:
        before = [(row.id, row.file_hash, row.triage_status, row.updated_at) for row in session.exec(select(Sample)).all()]
        revision = session.get(Dataset, ids["dataset"]).revision
    loaded = []
    def on_load(value, context):
        loaded.append(value.id)
    def no_disk(*args, **kwargs):
        raise AssertionError("Daily tools must not inspect original files")
    event.listen(Sample, "load", on_load)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "stat", no_disk); patch.setattr(Path, "iterdir", no_disk)
            assert client.get(f"/api/datasets/{ids['dataset']}/coverage").status_code == 200
            assert client.post(f"/api/datasets/{ids['dataset']}/filename-lookup", json={"entries": ["many.png"]}).status_code == 200
            assert loaded == []
            result = client.get(f"/api/datasets/{ids['dataset']}/coverage/samples", params={"category_id": ids["category"], "batch_id": ids["batch"], "page_size": 2})
            assert result.status_code == 200 and len(loaded) == 2
    finally:
        event.remove(Sample, "load", on_load)
    with Session(engine) as session:
        assert before == [(row.id, row.file_hash, row.triage_status, row.updated_at) for row in session.exec(select(Sample)).all()]
        assert session.get(Dataset, ids["dataset"]).revision == revision
