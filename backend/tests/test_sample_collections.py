from pathlib import Path
import sqlite3
from contextlib import closing

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.core import migrations
from app.main import app
from app.models.dataset import Dataset
from app.models.organization import DatasetCategory
from app.models.sample import Sample
from app.models.sample_collection import SampleCollection
from app.services import database_backup_service, workspace_backup_service


@pytest.fixture
def setup_collections():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = Dataset(name="First"); second = Dataset(name="Second")
        session.add_all([first, second]); session.flush()
        category = DatasetCategory(dataset_id=first.id, name="capsule")
        session.add(category); session.flush()
        samples = [Sample(dataset_id=dataset.id, category_id=category.id if index == 1 else None,
                          filename=f"{index}.png", absolute_path=f"/not-real/{index}.png", relative_path=f"{index}.png",
                          file_hash=str(index) * 64, extension=".png", file_type="image") for index, dataset in enumerate([first, second], 1)]
        session.add_all(samples); session.commit()
        ids = [sample.id for sample in samples]; dataset_ids = [first.id, second.id]; category_id = category.id

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    try:
        # No app lifespan: tests must not start the real workspace/runtime.
        yield TestClient(app), engine, ids, dataset_ids, category_id
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def test_basket_persistence_cross_dataset_and_conflict_without_truth_change(setup_collections):
    client, engine, ids, dataset_ids, _ = setup_collections
    before = client.get(f"/api/datasets/{dataset_ids[0]}").json()["revision"]
    response = client.post("/api/sample-collections", json={"name": "  讨论案例  ", "kind": "basket", "items": [{"sample_id": identity} for identity in ids]})
    assert response.status_code == 201, response.text
    basket = response.json()
    assert basket["name"] == "讨论案例"
    assert [item["dataset_id"] for item in basket["items"]] == dataset_ids
    assert all(item["unavailable_reason"] is None for item in basket["items"])
    assert client.get("/api/sample-collections", params={"kind": "basket"}).json() == [basket]
    saved = client.patch(f"/api/sample-collections/{basket['id']}", json={"expected_version": 1, "name": "讨论案例二", "items": [{"sample_id": ids[1], "note": "缺陷边界"}]}).json()
    assert saved["version"] == 2
    assert saved["items"][0]["note"] == "缺陷边界"
    stale = client.patch(f"/api/sample-collections/{basket['id']}", json={"expected_version": 1, "items": []})
    assert stale.status_code == 409
    assert client.delete(f"/api/sample-collections/{basket['id']}?expected_version=1").status_code == 409
    assert client.get(f"/api/datasets/{dataset_ids[0]}").json()["revision"] == before
    with Session(engine) as session:
        assert session.get(Sample, ids[0]).triage_status == "untriaged"
        assert session.get(Sample, ids[1]).triage_version == 0
    assert client.delete(f"/api/sample-collections/{basket['id']}?expected_version=2").status_code == 204
    assert client.get(f"/api/sample-collections/{basket['id']}").status_code == 404


def test_reference_scope_and_input_limits(setup_collections):
    client, _, ids, dataset_ids, category_id = setup_collections
    base = {"name": "验收口径", "kind": "reference", "dataset_id": dataset_ids[0], "category_id": category_id}
    assert client.post("/api/sample-collections", json={**base, "dataset_id": None}).status_code == 422
    assert client.post("/api/sample-collections", json={**base, "items": [{"sample_id": ids[0]}]}).status_code == 422
    assert client.post("/api/sample-collections", json={**base, "items": [{"sample_id": ids[1], "verdict": "acceptable"}]}).status_code == 422
    response = client.post("/api/sample-collections", json={**base, "items": [{"sample_id": ids[0], "verdict": "acceptable", "note": "轻微反光可接受"}]})
    assert response.status_code == 201, response.text
    assert client.get("/api/sample-collections", params={"kind": "reference", "dataset_id": dataset_ids[0], "category_id": category_id}).json() == [response.json()]
    assert client.get("/api/sample-collections", params={"kind": "reference", "dataset_id": dataset_ids[1]}).json() == []
    assert client.post("/api/sample-collections", json={"name": " ", "kind": "basket"}).status_code == 422
    assert client.post("/api/sample-collections", json={"name": "重复", "items": [{"sample_id": ids[0]}] * 2}).status_code == 422
    assert client.post("/api/sample-collections", json={"name": "过量", "items": [{"sample_id": ids[0]}] * 101}).status_code == 422
    assert client.post("/api/sample-collections", json={"name": "失效", "items": [{"sample_id": 9999}]}).status_code == 422
    assert client.post("/api/sample-collections", json={"name": "错hash", "items": [{"sample_id": ids[0], "file_hash": "wrong"}]}).status_code == 409


def test_stale_deleted_and_moved_samples_remain_visible_without_refreshing_reference(setup_collections):
    client, engine, ids, dataset_ids, category_id = setup_collections
    basket = client.post("/api/sample-collections", json={"name": "要保留的清单", "items": [{"sample_id": identity} for identity in ids]}).json()
    with Session(engine) as session:
        session.get(Sample, ids[0]).file_hash = "new"
        session.delete(session.get(Sample, ids[1])); session.commit()
    read = client.get(f"/api/sample-collections/{basket['id']}").json()
    assert "已变化" in read["items"][0]["unavailable_reason"]
    assert read["items"][1]["sample"] is None
    assert "已删除" in read["items"][1]["unavailable_reason"]
    updated = client.patch(f"/api/sample-collections/{basket['id']}", json={"expected_version": 1, "items": [{"sample_id": ids[0], "note": "编辑说明仍保留旧hash"}, {"sample_id": ids[1]}]}).json()
    assert updated["items"][0]["file_hash"] == "1" * 64
    assert updated["items"][1]["filename"] == "2.png"
    assert client.patch(f"/api/sample-collections/{basket['id']}", json={"expected_version": 2, "items": [{"sample_id": ids[0], "file_hash": "new"}]}).status_code == 409
    # Removing a dataset must not be blocked by a collection foreign key.
    assert client.delete(f"/api/datasets/{dataset_ids[0]}").status_code == 204
    retained = client.get(f"/api/sample-collections/{basket['id']}").json()
    assert retained["items"][0]["sample"] is None


def test_old_schema_returns_actionable_503(setup_collections):
    client, engine, _, _, _ = setup_collections
    SampleCollection.__table__.drop(engine)
    response = client.get("/api/sample-collections")
    assert response.status_code == 503
    assert "离线迁移" in response.json()["detail"]


def test_unassigned_reference_scope_stays_unassigned_after_category_change(setup_collections):
    client, engine, ids, dataset_ids, category_id = setup_collections
    payload = {"name": "未分类参考", "kind": "reference", "dataset_id": dataset_ids[0],
        "items": [{"sample_id": ids[0], "verdict": "uncertain"}]}
    # A null category is the unassigned scope used by the reference-card UI.
    assert client.post("/api/sample-collections", json=payload).status_code == 422
    with Session(engine) as session:
        session.get(Sample, ids[0]).category_id = None
        session.commit()
    created = client.post("/api/sample-collections", json=payload)
    assert created.status_code == 201, created.text
    reference = created.json()
    with Session(engine) as session:
        session.get(Sample, ids[0]).category_id = category_id
        session.commit()
    changed = client.get(f"/api/sample-collections/{reference['id']}").json()
    assert "已不属于" in changed["items"][0]["unavailable_reason"]


def test_migration_and_backup_preserve_collections(tmp_path: Path):
    path = tmp_path / "isolated.db"
    command.upgrade(migrations.alembic_config(path), "20261106_0014")
    with closing(sqlite3.connect(path)) as connection:
        before_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "sample_collections" not in before_tables
    result = migrations.upgrade_database(path)
    assert result.backup is not None and result.current_revision == migrations.head_revision()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO sample_collections(name,kind,version,items_json,created_at,updated_at) VALUES('持久案例','basket',1,'[]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        connection.commit()
    backup = migrations.create_verified_backup(path)
    verification = database_backup_service._inspect_backup(Path(backup.backup_path))
    assert verification["table_counts"]["sample_collections"] == 1
    before = workspace_backup_service._source_signature(path, -1)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE sample_collections SET version=2")
        connection.commit()
    assert workspace_backup_service._source_signature(path, -1) != before
