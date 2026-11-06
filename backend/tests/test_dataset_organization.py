import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core import migrations
from app.core.database import get_session
from app.main import app
from app.models.dataset import Dataset
from app.models.sample import Sample


@pytest.fixture
def organization_client(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.services import industrial_plan_service
    settings = get_settings().model_copy(update={"storage_root": tmp_path / "storage"})
    monkeypatch.setattr(industrial_plan_service, "get_settings", lambda: settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    def override():
        with Session(engine) as session:
            yield session
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = override
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def new_dataset(client, **values):
    response = client.post("/api/datasets", json={"name": "Images", **values})
    assert response.status_code == 201, response.text
    return response.json()


def add_sample(engine, dataset_id, **values):
    with Session(engine) as session:
        sample = Sample(dataset_id=dataset_id, filename="part.png", absolute_path=f"/raw/{dataset_id}/part.png",
            relative_path="part.png", file_type="image", extension=".png", file_hash="a"*64, **values)
        session.add(sample)
        session.commit()
        return sample.id


def test_projects_create_attach_rename_and_legacy_string_compatibility(organization_client):
    client, _ = organization_client
    project = client.post("/api/projects", json={"name": " 探针 ", "description": "Inspection"}).json()
    first = new_dataset(client, project_id=project["id"])
    second = new_dataset(client, project="探针")
    assert first["project"] == second["project"] == "探针"
    assert first["project_id"] == second["project_id"] == project["id"]
    assert client.get("/api/projects").json()[0]["dataset_count"] == 2
    assert client.post("/api/projects", json={"name": "探针"}).status_code == 409
    assert client.patch(f"/api/projects/{project['id']}", json={"name": "探针检测"}).status_code == 200
    assert client.get(f"/api/datasets/{first['id']}").json()["project"] == "探针检测"
    assert client.delete(f"/api/projects/{project['id']}").status_code == 409
    for dataset in (first, second):
        assert client.patch(f"/api/datasets/{dataset['id']}", json={"project_id": None}).status_code == 200
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.post("/api/projects", json={"name": " "}).status_code == 422


def test_category_batch_assignment_preserves_group_judgment_and_unmentioned_fields(organization_client):
    client, engine = organization_client
    dataset = new_dataset(client)
    sample_id = add_sample(engine, dataset["id"], capture_group_id="real-part-1", capture_batch_id="legacy",
        triage_status="ok", ok_grade="clear", split="test")
    path = f"/api/datasets/{dataset['id']}"
    category = client.post(path+"/categories", json={"name": "bottle"}).json()
    batch = client.post(path+"/batches", json={"name": "首次采集", "captured_at": "2026-11-06"}).json()
    assigned = client.patch(path+"/organization/assign", json={"sample_ids": [sample_id], "batch_id": batch["id"]})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["updated_count"] == 1
    assert client.patch(path+"/organization/assign", json={"sample_ids": [sample_id], "category_id": category["id"]}).status_code == 200
    sample = client.get(f"/api/samples/{sample_id}").json()
    assert sample["batch_id"] == batch["id"] and sample["category_id"] == category["id"]
    assert sample["capture_batch_id"] == batch["code"]
    assert (sample["capture_group_id"], sample["triage_status"], sample["ok_grade"], sample["split"]) == ("real-part-1", "ok", "clear", "test")
    organization = client.get(path+"/organization").json()
    assert organization["categories"][0]["sample_count"] == organization["categories"][0]["normal_count"] == 1
    assert organization["categories"][0]["cover_sample_id"] == sample_id
    assert organization["batches"][0]["sample_count"] == 1
    assert client.delete(path+f"/categories/{category['id']}").status_code == 409
    assert client.delete(path+f"/batches/{batch['id']}").status_code == 409
    renamed = client.patch(path+f"/batches/{batch['id']}", json={"name": "首次采集（确认）"}).json()
    assert renamed["code"] == batch["code"]
    assert client.get(f"/api/samples/{sample_id}").json()["capture_batch_id"] == batch["code"]
    assert client.patch(path+"/organization/assign", json={"sample_ids": [sample_id], "category_id": None}).status_code == 200
    assert client.delete(path+f"/categories/{category['id']}").status_code == 204
    assert client.get(f"/api/samples/{sample_id}").json()["batch_id"] == batch["id"]


def test_organization_assignment_rejects_cross_dataset_and_is_atomic(organization_client):
    client, engine = organization_client
    first, second = new_dataset(client), new_dataset(client)
    sample = add_sample(engine, first["id"], capture_group_id="keep")
    foreign = add_sample(engine, second["id"])
    first_path, second_path = f"/api/datasets/{first['id']}", f"/api/datasets/{second['id']}"
    batch = client.post(first_path+"/batches", json={"name": "B001"}).json()
    category = client.post(second_path+"/categories", json={"name": "other"}).json()
    for values in ({"sample_ids": [sample], "category_id": category["id"]},
                   {"sample_ids": [sample, foreign], "batch_id": batch["id"]},
                   {"sample_ids": [sample], "batch_id": 999999}):
        assert client.patch(first_path+"/organization/assign", json=values).status_code in (404, 422)
    assert client.get(f"/api/samples/{sample}").json()["batch_id"] is None
    assert client.patch(first_path+"/organization/assign", json={"sample_ids": [sample]}).status_code == 422
    assert client.patch(first_path+f"/categories/{category['id']}", json={"name": "bad"}).status_code == 404
    assert client.post(first_path+"/categories", json={"name": "same"}).status_code == 201
    assert client.post(first_path+"/categories", json={"name": "same"}).status_code == 409
    assert client.get(first_path+"/categories").status_code == 200


def test_delete_dataset_removes_organization_children_but_retains_project(organization_client):
    client, _ = organization_client
    dataset = new_dataset(client, project="Keep project")
    path = f"/api/datasets/{dataset['id']}"
    client.post(path+"/categories", json={"name": "part"})
    client.post(path+"/batches", json={"name": "batch"})
    assert client.delete(path).status_code == 204
    assert client.get("/api/projects").json()[0]["dataset_count"] == 0


def test_sample_organization_fields_are_optional_and_serialized(organization_client):
    client, engine = organization_client
    dataset = new_dataset(client)
    sample = add_sample(engine, dataset["id"], import_format="mvtec_ad", official_split="test",
        benchmark_label="anomaly", benchmark_defect_type="broken", mask_path="/raw/masks/part.png")
    result = client.get(f"/api/samples/{sample}").json()
    assert result["import_format"] == "mvtec_ad" and result["official_split"] == "test"
    assert result["benchmark_label"] == "anomaly" and result["mask_path"] == "/raw/masks/part.png"


def test_legacy_group_editor_keeps_batch_relation_in_sync(organization_client):
    from app.schemas.industrial import GroupPreviewRequest, PlanConfirmation
    from app.services import capture_group_service

    client, engine = organization_client
    dataset = new_dataset(client)
    first = add_sample(engine, dataset["id"])
    with Session(engine) as session:
        second = Sample(dataset_id=dataset["id"], filename="second.png", absolute_path="/raw/second.png",
            relative_path="second.png", file_type="image", extension=".png", file_hash="b"*64)
        session.add(second)
        session.commit()
        second_id = second.id
    def apply_batch(code):
        with Session(engine) as session:
            plan = capture_group_service.preview(session, dataset["id"], GroupPreviewRequest(
                mode="selected", sample_ids=[first, second_id], capture_group_id="part-1", capture_batch_id=code))
            capture_group_service.confirm(session, dataset["id"], plan["plan_id"], PlanConfirmation(
                plan_hash=plan["plan_hash"], confirmation=plan["confirmation"]))
    apply_batch("legacy-batch")
    items = [client.get(f"/api/samples/{sample_id}").json() for sample_id in [first, second_id]]
    batches = client.get(f"/api/datasets/{dataset['id']}/batches").json()
    assert len(batches) == 1 and batches[0]["code"] == "legacy-batch"
    assert all(item["batch_id"] == batches[0]["id"] and item["capture_group_id"] == "part-1" for item in items)
    apply_batch(None)
    assert all(client.get(f"/api/samples/{sample_id}").json()["batch_id"] is None for sample_id in [first, second_id])
    apply_batch("legacy-batch")
    assert len(client.get(f"/api/datasets/{dataset['id']}/batches").json()) == 1


def test_organization_migration_backfills_legacy_without_rewriting_original_fields(tmp_path: Path):
    path = tmp_path/"legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES ('20261101_0013');
            CREATE TABLE datasets(id INTEGER PRIMARY KEY,name TEXT,project TEXT,revision INTEGER);
            INSERT INTO datasets VALUES (1,'Probe first','探针',9),(2,'Probe second','探针',4),(3,'Other',NULL,2);
            CREATE TABLE samples(id INTEGER PRIMARY KEY,dataset_id INTEGER,relative_path TEXT,
                capture_batch_id TEXT,capture_group_id TEXT,triage_status TEXT,split TEXT,file_hash TEXT);
            INSERT INTO samples VALUES (11,1,'a.png','B001','part-a','ok','train','keep-hash');
            INSERT INTO samples VALUES (12,1,'b.png','B001','part-a','ng','test','keep-other');
            INSERT INTO samples VALUES (13,2,'c.png','B001','part-b','pending',NULL,'keep-third');
            INSERT INTO samples VALUES (14,3,'d.png',NULL,NULL,'untriaged',NULL,'keep-fourth');
            CREATE TABLE original_annotations(sample_id INTEGER,value TEXT);
            INSERT INTO original_annotations VALUES (11,'retain geometry');
        """)
        before = connection.execute("SELECT * FROM samples ORDER BY id").fetchall()
    connection.close()
    result = migrations.upgrade_database(path, backup_dir=tmp_path/"backups")
    assert result.backup is not None
    assert Path(result.backup.backup_path).exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM dataset_batches").fetchone()[0] == 2
        assert connection.execute("SELECT project_id FROM datasets WHERE id=3").fetchone()[0] is None
        after = connection.execute("SELECT id,dataset_id,relative_path,capture_batch_id,capture_group_id,triage_status,split,file_hash FROM samples ORDER BY id").fetchall()
        assert after == before
        assert connection.execute("SELECT revision FROM datasets ORDER BY id").fetchall() == [(9,), (4,), (2,)]
        ids = connection.execute("SELECT batch_id FROM samples ORDER BY id").fetchall()
        assert ids[0] == ids[1] and ids[0] != ids[2] and ids[3] == (None,)
        assert connection.execute("SELECT value FROM original_annotations").fetchone()[0] == "retain geometry"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
    assert migrations.upgrade_database(path).changed is False
