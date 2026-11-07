from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.workpiece import router
from app.core.database import get_session
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.services import anomaly_protocol_service, workpiece


@pytest.fixture
def workpiece_client(tmp_path: Path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Parts", workflow_profile="industrial_anomaly", triage_policy_version=2, revision=7)
        foreign = Dataset(name="Other", triage_policy_version=2)
        session.add_all([dataset, foreign])
        session.flush()
        identities = {"dataset": dataset.id, "foreign_dataset": foreign.id}
        index = 0

        def add(name: str, *, dataset_id=dataset.id, group="part", batch="first", **extra):
            nonlocal index
            index += 1
            digest = f"{index:064x}"
            path = tmp_path / name
            path.write_bytes(f"source-{index}".encode())
            fields = dict(dataset_id=dataset_id, filename=name, relative_path=name,
                absolute_path=str(path), extension=".png", file_type="image", file_hash=digest,
                capture_group_id=group, capture_batch_id=batch, triage_status="ok", ok_grade="clear",
                triaged_file_hash=digest, triage_policy_version=2)
            fields.update(extra)
            sample = Sample(**fields)
            session.add(sample)
            session.flush()
            return sample.id

        identities["views"] = [add(f"view-{number:02}.png") for number in range(14)]
        identities["second"] = [add(f"second-{number}.png", batch="second") for number in range(2)]
        identities["no_batch"] = [add(f"no-batch-{number}.png", batch=None) for number in range(2)]
        identities["ungrouped"] = add("ungrouped.png", group=None)
        identities["foreign"] = add("foreign.png", dataset_id=foreign.id)
        identities["table"] = add("table.csv", group=None, file_type="table", extension=".csv")
        session.commit()

    api = FastAPI()
    api.include_router(router)

    def override():
        with Session(engine) as session:
            yield session

    api.dependency_overrides[get_session] = override
    with TestClient(api) as client:
        yield client, engine, identities
    engine.dispose()


def url(sample_id: int) -> str:
    return f"/api/samples/{sample_id}/workpiece-views"


def test_workpiece_matches_dataset_group_and_batch_and_pages(workpiece_client):
    client, _, ids = workpiece_client
    first = client.get(url(ids["views"][0])).json()
    assert first["dataset_id"] == ids["dataset"]
    assert first["anchor_sample_id"] == ids["views"][0]
    assert first["capture_group_id"] == "part" and first["capture_batch_id"] == "first"
    assert first["dataset_revision"] == 7 and first["total"] == 14
    assert first["page"] == 1 and first["page_size"] == 12
    assert [item["id"] for item in first["items"]] == ids["views"][:12]
    assert first["isolation"] == {"total": 14, "normal_candidate": True, "reasons": {}}
    last = client.get(url(ids["views"][0]), params={"page": 99}).json()
    assert last["page"] == 2
    assert [item["id"] for item in last["items"]] == ids["views"][12:]
    second = client.get(url(ids["second"][0])).json()
    assert {item["id"] for item in second["items"]} == set(ids["second"])
    assert second["isolation"]["total"] == 2


def test_unassigned_batch_and_group_are_not_wildcards(workpiece_client):
    client, _, ids = workpiece_client
    no_batch = client.get(url(ids["no_batch"][0])).json()
    assert {item["id"] for item in no_batch["items"]} == set(ids["no_batch"])
    assert no_batch["capture_batch_id"] is None
    ungrouped = client.get(url(ids["ungrouped"])).json()
    assert [item["id"] for item in ungrouped["items"]] == [ids["ungrouped"]]
    assert ungrouped["isolation"] == {"total": 1, "normal_candidate": False,
        "reasons": {"缺少工件组，尚未确认独立采集": 1}}


def test_hash_bridge_changes_isolation_without_polluting_workpiece_views(workpiece_client):
    client, engine, ids = workpiece_client
    with Session(engine) as session:
        anchor = session.get(Sample, ids["views"][0])
        bridge = session.get(Sample, ids["second"][0])
        bridge.file_hash = bridge.triaged_file_hash = anchor.file_hash
        bridge.triage_status = "ng"
        bridge.ok_grade = None
        # An identical hash in a different dataset must remain outside this graph.
        foreign = session.get(Sample, ids["foreign"])
        foreign.file_hash = foreign.triaged_file_hash = anchor.file_hash
        session.add_all([bridge, foreign])
        session.commit()
    data = client.get(url(ids["views"][0]), params={"page_size": 24}).json()
    assert {item["id"] for item in data["items"]} == set(ids["views"])
    assert data["isolation"]["total"] == 16
    assert data["isolation"]["normal_candidate"] is False
    assert data["isolation"]["reasons"] == {
        "包含 NG 异常，整组不能用于纯正常训练": 1,
        "相同内容的正常/异常判定矛盾": 2,
    }


def test_entire_isolation_group_affects_eligibility_including_hidden_page(workpiece_client):
    client, engine, ids = workpiece_client
    with Session(engine) as session:
        changes = [
            (13, {"file_status": "missing"}),
            (12, {"triaged_file_hash": "old-content"}),
            (11, {"triage_policy_version": 1}),
            (10, {"triage_status": "pending", "ok_grade": None}),
            (9, {"ok_grade": "borderline"}),
            (8, {"ok_grade": None}),
        ]
        for number, fields in changes:
            sample = session.get(Sample, ids["views"][number])
            for key, value in fields.items():
                setattr(sample, key, value)
            session.add(sample)
        session.commit()
    first = client.get(url(ids["views"][0]), params={"page_size": 2}).json()
    assert len(first["items"]) == 2 and first["isolation"]["normal_candidate"] is False
    assert first["isolation"]["reasons"] == {
        "文件不可用或不是图片": 1,
        "判定已过期，需复核": 2,
        "未分拣或待定": 1,
        "临界 OK 默认排除": 1,
        "统一 OK 尚未确认正常等级": 1,
    }
    last = client.get(url(ids["views"][0]), params={"page": 7, "page_size": 2}).json()
    assert last["items"][0]["triage_outdated"] is True
    assert last["items"][1]["file_status"] == "missing"
    assert last["isolation"] == first["isolation"]


def test_view_rejects_unknown_nonimage_and_invalid_pagination(workpiece_client):
    client, _, ids = workpiece_client
    assert client.get(url(999999)).status_code == 404
    assert client.get(url(ids["table"])).status_code == 422
    for query in ({"page": 0}, {"page_size": 0}, {"page_size": 25}):
        assert client.get(url(ids["views"][0]), params=query).status_code == 422


def test_view_is_read_only_and_does_not_read_source_files(workpiece_client, monkeypatch):
    client, engine, ids = workpiece_client
    with Session(engine) as session:
        before = {sample.id: sample.model_dump() for sample in session.exec(select(Sample)).all()}
        dataset_before = session.get(Dataset, ids["dataset"]).model_dump()
    source_before = {row["absolute_path"]: Path(row["absolute_path"]).read_bytes() for row in before.values()}

    def reject_file_check(*_args, **_kwargs):
        raise AssertionError("The read-only workpiece metadata query must not inspect source bytes")

    monkeypatch.setattr(anomaly_protocol_service, "image_is_decodable", reject_file_check)
    monkeypatch.setattr(anomaly_protocol_service, "file_digest", reject_file_check)
    writes = []

    def record_write(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record_write)
    try:
        response = client.get(url(ids["views"][0]))
        assert response.status_code == 200, response.text
    finally:
        event.remove(engine, "before_cursor_execute", record_write)
    assert writes == []
    with Session(engine) as session:
        assert {sample.id: sample.model_dump() for sample in session.exec(select(Sample)).all()} == before
        assert session.get(Dataset, ids["dataset"]).model_dump() == dataset_before
    assert {path: Path(path).read_bytes() for path in source_before} == source_before


def test_capacity_limit_is_dataset_local(workpiece_client, monkeypatch):
    client, _, ids = workpiece_client
    monkeypatch.setattr(workpiece, "MAX_DATASET_SAMPLES", 3)
    rejected = client.get(url(ids["views"][0]))
    assert rejected.status_code == 422 and "10000" in rejected.json()["detail"]
    # The foreign dataset has just one member, regardless of the main dataset.
    assert client.get(url(ids["foreign"])).status_code == 200
