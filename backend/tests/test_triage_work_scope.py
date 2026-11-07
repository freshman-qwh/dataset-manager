from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.triage import router
from app.core.database import get_session
from app.models.dataset import Dataset
from app.models.sample import Sample


@pytest.fixture
def work_client() -> Iterator[tuple[TestClient, object, dict[str, int]]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Work", triage_policy_version=2, revision=7)
        foreign = Dataset(name="Foreign")
        session.add_all([dataset, foreign])
        session.flush()
        ids = {"dataset": dataset.id, "foreign": foreign.id}
        for index, (name, fields) in enumerate([
            ("a.png", {}),
            ("same.png", {}),
            ("same.png", {}),
            ("pending.png", {"triage_status": "pending", "split": "test"}),
            ("missing.png", {"file_status": "missing"}),
            ("foreign.png", {"dataset_id": foreign.id}),
            ("notes.txt", {"file_type": "text"}),
        ]):
            values = dict(dataset_id=dataset.id, filename=name, relative_path=name,
                          absolute_path=f"C:/work/{index}/{name}", extension=".png",
                          file_type="image", file_hash=f"{index:064x}")
            values.update(fields)
            sample = Sample(**values)
            session.add(sample)
            session.flush()
            ids[f"sample{index}"] = sample.id
        session.commit()
    api = FastAPI()
    api.include_router(router)

    def override_session():
        with Session(engine) as session:
            yield session

    api.dependency_overrides[get_session] = override_session
    with TestClient(api) as client:
        yield client, engine, ids
    engine.dispose()


def test_fixed_scope_keeps_saved_samples_and_excludes_later_additions(work_client) -> None:
    client, engine, ids = work_client
    base = f"/api/datasets/{ids['dataset']}/triage"
    scope = client.post(f"{base}/work-scope", json={})
    assert scope.status_code == 200
    frozen = scope.json()
    assert frozen["sample_ids"] == [ids["sample0"], ids["sample1"], ids["sample2"]]
    assert frozen["dataset_revision"] == 7
    assert frozen["dataset_created_at"]
    with Session(engine) as session:
        sample = session.get(Sample, ids["sample0"])
        sample.triage_status = "ok"
        sample.triage_version = 1
        sample.triaged_file_hash = sample.file_hash
        sample.triage_policy_version = 2
        session.add(sample)
        session.add(Sample(dataset_id=ids["dataset"], filename="new.png", relative_path="new.png",
                           absolute_path="C:/work/new.png", extension=".png", file_type="image", file_hash="new"))
        session.commit()
    nav = client.post(f"{base}/work-navigation", json={"sample_ids": frozen["sample_ids"]}).json()
    assert nav["total"] == 3
    assert nav["current_sample"]["triage_status"] == "ok"
    assert nav["current_sample"]["id"] == ids["sample0"]
    next_nav = client.post(f"{base}/work-navigation", json={
        "sample_ids": frozen["sample_ids"], "target_index": 3,
    }).json()
    assert next_nav["current_sample"]["id"] == ids["sample2"]
    assert next_nav["previous_sample"]["id"] == ids["sample1"]
    assert next_nav["next_sample"] is None
    assert next_nav["current_index"] == 2
    # Read-only calls do not bump the dataset or touch source files.
    with Session(engine) as session:
        assert session.get(Dataset, ids["dataset"]).revision == 7


def test_navigation_and_state_isolate_dataset_and_skip_deleted_samples(work_client) -> None:
    client, engine, ids = work_client
    base = f"/api/datasets/{ids['dataset']}/triage"
    with Session(engine) as session:
        session.delete(session.get(Sample, ids["sample0"]))
        session.commit()
    sample_ids = [ids["sample0"], ids["sample1"], ids["sample1"], ids["sample5"], ids["sample6"]]
    nav = client.post(f"{base}/work-navigation", json={"sample_ids": sample_ids}).json()
    assert nav["total"] == 1
    assert nav["current_sample"]["id"] == ids["sample1"]
    state = client.post(f"{base}/work-state", json={"sample_ids": sample_ids}).json()
    assert [item["sample_id"] for item in state["items"]] == [ids["sample1"]]
    empty = client.post(f"{base}/work-navigation", json={"sample_ids": []}).json()
    assert empty["total"] == 0
    assert empty["current_sample"] is None


def test_scope_reuses_filters_and_infers_current_split(work_client) -> None:
    client, _, ids = work_client
    base = f"/api/datasets/{ids['dataset']}/triage"
    for payload, expected in [
        ({"queue_scope": "pending"}, [ids["sample3"]]),
        ({"queue_scope": "current_split", "sample_id": ids["sample3"]}, [ids["sample3"]]),
        ({"queue_scope": "current_filter", "search": "SAME"}, [ids["sample1"], ids["sample2"]]),
        ({"queue_scope": "current_filter", "triage_status": "pending"}, [ids["sample3"]]),
    ]:
        result = client.post(f"{base}/work-scope", json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["sample_ids"] == expected
    assert client.post(f"{base}/work-scope", json={"queue_scope": "current_split"}).status_code == 422
    assert client.post(f"{base}/work-scope", json={"queue_scope": "current_filter", "ok_grade": "clear"}).status_code == 422
    assert client.post(f"{base}/work-scope", json={"triage_status": "invalid"}).status_code == 422
    assert client.post(f"{base}/work-scope", json={"queue_scope": "invalid"}).status_code == 422
    assert client.post(f"{base}/work-scope", json={"queue_scope": "current_filter", "defect_type_id": 9}).status_code == 422


def test_state_reports_external_changes_policy_expiry_and_unavailable_files(work_client) -> None:
    client, engine, ids = work_client
    base = f"/api/datasets/{ids['dataset']}/triage"
    with Session(engine) as session:
        sample = session.get(Sample, ids["sample0"])
        sample.triage_version = 3
        sample.triage_status = "ng"
        sample.triaged_file_hash = sample.file_hash
        sample.triage_policy_version = 2
        session.add(sample)
        session.commit()
    payload = {"sample_ids": [ids["sample0"], ids["sample4"]]}
    state = client.post(f"{base}/work-state", json=payload).json()
    by_id = {row["sample_id"]: row for row in state["items"]}
    assert by_id[ids["sample0"]]["triage_version"] == 3
    assert by_id[ids["sample0"]]["triage_status"] == "ng"
    assert by_id[ids["sample0"]]["triage_outdated"] is False
    assert by_id[ids["sample4"]]["file_status"] == "missing"
    with Session(engine) as session:
        dataset = session.get(Dataset, ids["dataset"])
        dataset.triage_policy_version = 3
        session.add(dataset)
        session.commit()
    state = client.post(f"{base}/work-state", json=payload).json()
    assert next(row for row in state["items"] if row["sample_id"] == ids["sample0"])["triage_outdated"] is True


@pytest.mark.parametrize("sample_ids", [[0], [-1], [True], ["1"], [1] * 10001])
def test_work_requests_reject_invalid_or_oversized_id_lists(work_client, sample_ids) -> None:
    client, _, ids = work_client
    base = f"/api/datasets/{ids['dataset']}/triage"
    for endpoint in ["work-navigation", "work-state"]:
        assert client.post(f"{base}/{endpoint}", json={"sample_ids": sample_ids}).status_code == 422


def test_scope_rejects_more_than_ten_thousand_images(work_client) -> None:
    client, engine, ids = work_client
    with Session(engine) as session:
        session.add_all([Sample(dataset_id=ids["dataset"], filename=f"{index}.png", relative_path=f"{index}.png",
                                absolute_path=f"C:/capacity/{index}.png", extension=".png", file_type="image",
                                file_hash=f"capacity{index}") for index in range(10001)])
        session.commit()
    result = client.post(f"/api/datasets/{ids['dataset']}/triage/work-scope", json={})
    assert result.status_code == 422
    assert "10000" in result.json()["detail"]
