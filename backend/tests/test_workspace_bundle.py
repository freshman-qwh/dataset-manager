import json
import sqlite3
import threading
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.core import migrations
from app.core.config import get_settings
from app.core.database import get_session
from app.main import app
from app.services import industrial_example_service, dataset_snapshot_service, workspace_backup_service as backups, job_artifact_service, job_service
from app.services.job_runner import JobContext


def fixture_bundle(tmp_path, monkeypatch, organization=False):
    database = tmp_path / "source.db"
    migrations.upgrade_database(database)
    engine = create_engine(f"sqlite:///{database.as_posix()}", connect_args={"check_same_thread": False})
    def session_override():
        with Session(engine) as session: yield session
    app.dependency_overrides[get_session] = session_override
    storage = tmp_path / "source-storage"
    settings = get_settings().model_copy(update={"database_path": database, "storage_root": storage})
    monkeypatch.setattr(backups, "get_settings", lambda: settings)
    monkeypatch.setattr(industrial_example_service, "get_settings", lambda: settings)
    monkeypatch.setattr(dataset_snapshot_service, "_snapshot_root", lambda: storage / "snapshots")
    monkeypatch.setattr(job_artifact_service, "job_artifact_root", lambda: tmp_path / "artifacts")
    client = TestClient(app)
    dataset = client.post("/api/datasets/industrial-example").json()
    snapshot = client.post(f"/api/datasets/{dataset['id']}/snapshots", json={"name": "frozen"})
    assert snapshot.status_code == 201, snapshot.text
    from app.services import validation_run_service, validation_runtime_service, industrial_plan_service
    from app.schemas.validation import RuntimeRead
    from test_validation_results import completed_run
    monkeypatch.setattr(validation_run_service,"get_settings",lambda:settings)
    monkeypatch.setattr(industrial_plan_service,"get_settings",lambda:settings)
    monkeypatch.setattr(validation_runtime_service,"status",lambda *args:RuntimeRead(ready=True,message="test"))
    completed_run(client,engine,dataset)
    if organization:
        from app.models.organization import Project, DatasetCategory, DatasetBatch
        from app.models.dataset import Dataset
        from app.models.sample import Sample
        from sqlmodel import select
        with Session(engine) as session:
            project = Project(name="probe")
            category = DatasetCategory(dataset_id=dataset["id"], name="probe-A")
            batch = DatasetBatch(dataset_id=dataset["id"], name="first-capture")
            session.add_all([project, category, batch]); session.flush()
            stored_dataset = session.get(Dataset, dataset["id"])
            stored_dataset.project_id = project.id; stored_dataset.project = project.name
            sample = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"]).order_by(Sample.id)).first()
            sample.category_id = category.id; sample.batch_id = batch.id; sample.capture_batch_id = batch.code
            sample.import_format = "mvtec_ad"; sample.official_split = "test"; sample.benchmark_label = "anomaly"
            sample.mask_path = str(tmp_path / "original-mask.png")
            session.add(stored_dataset); session.add(sample); session.commit()
    (storage / "job-recovery").mkdir()
    (storage / "job-recovery" / "recovery.json").write_text('{"test": true}', encoding="utf-8")
    with Session(engine) as session:
        job = backups.create_job(session).job
        job = job_service.transition_job(session, job.id, "running")
    result = backups.run_backup(JobContext(job.id, engine, threading.Event()), job.parameters)
    archive = job_artifact_service.resolve_job_artifact(tmp_path / "artifacts", job_id=job.id, filename=result["artifact"]["filename"])
    return archive, database, storage, result


def test_restore_to_new_location_verifies_database_and_external_snapshots(tmp_path: Path, monkeypatch):
    archive, source_db, storage, result = fixture_bundle(tmp_path, monkeypatch)
    target = tmp_path / "新工作区 中文路径"
    restored = backups.restore_bundle(archive, target)
    assert restored["verification"]["table_counts"]["samples"] == 16
    assert restored["verification"]["table_counts"]["dataset_snapshots"] == 1
    assert restored["verification"]["table_counts"]["validation_runs"] == 1
    assert next((target/"storage/validation-runs").rglob("model.pt")).read_bytes()==b"frozen model"
    assert restored["current_workspace_replaced"] is False
    assert not (target / "storage/datasets").exists()
    assert len(list((target / "storage/snapshots").rglob("*.json"))) == 1
    assert (target / "storage/job-recovery/recovery.json").is_file()
    assert source_db.is_file()
    with pytest.raises(ValueError, match="新目录"):
        backups.restore_bundle(archive, target)


def test_restore_preserves_organization_and_external_mask_references(tmp_path, monkeypatch):
    archive, source_db, storage, result = fixture_bundle(tmp_path, monkeypatch, organization=True)
    target = tmp_path / "organized-restore"
    restored = backups.restore_bundle(archive, target)
    counts = restored["verification"]["table_counts"]
    assert counts["projects"] == counts["dataset_categories"] == counts["dataset_batches"] == 1
    with sqlite3.connect(target / "database/app.db") as connection:
        row = connection.execute("SELECT category_id,batch_id,import_format,official_split,mask_path FROM samples WHERE category_id IS NOT NULL").fetchone()
        assert row[:4] == (1, 1, "mvtec_ad", "test")
        assert row[4] == str(tmp_path / "original-mask.png")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("corruption", ["content", "missing", "traversal"])
def test_corrupt_bundle_never_publishes_restored_workspace(tmp_path: Path, monkeypatch, corruption):
    archive, _, _, _ = fixture_bundle(tmp_path, monkeypatch)
    bad = tmp_path / "bad.zip"
    with ZipFile(archive) as source, ZipFile(bad, "w") as destination:
        for name in source.namelist():
            if corruption == "missing" and name.startswith("storage/snapshots/"): continue
            value = source.read(name)
            if corruption == "content" and name.startswith("storage/snapshots/"): value = b"tampered"
            destination.writestr(name, value)
        if corruption == "traversal": destination.writestr("../outside.txt", "unsafe")
    target = tmp_path / "new-workspace"
    with pytest.raises((ValueError, KeyError)):
        backups.restore_bundle(bad, target)
    assert not target.exists()
    assert not (tmp_path / "outside.txt").exists()
    assert not list(tmp_path.glob("*.part"))


def test_startup_status_identifies_legacy_schema_without_writing_it(tmp_path: Path, monkeypatch):
    from app.api import system
    from test_dataset_api import make_client
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE datasets(id INTEGER PRIMARY KEY)")
    settings = get_settings().model_copy(update={"database_path": database, "storage_root": tmp_path / "storage"})
    monkeypatch.setattr(system, "get_settings", lambda: settings)
    client = make_client()
    response = client.get("/api/system/startup-status")
    assert response.status_code == 200
    assert response.json()["needs_upgrade"] is True
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(datasets)")}
    assert columns == {"id"}
    invalid_archive = tmp_path / "bad.zip"
    invalid_archive.write_bytes(b"not a zip")
    assert client.post("/api/system/restore-workspace", json={"archive_path": str(invalid_archive)}).status_code == 422


def test_restore_rejects_model_inconsistent_with_frozen_result(tmp_path,monkeypatch):
    import hashlib
    archive,_,_,_=fixture_bundle(tmp_path,monkeypatch)
    bad=tmp_path/"model-inconsistent.zip"
    with ZipFile(archive) as source,ZipFile(bad,"w") as destination:
        manifest=json.loads(source.read("bundle-manifest.json"))
        for item in manifest["files"]:
            value=source.read(item["path"])
            if item["path"].endswith("/model.pt"):
                value=b"different model"
                item.update(sha256=hashlib.sha256(value).hexdigest(),size_bytes=len(value))
            destination.writestr(item["path"],value)
        destination.writestr("bundle-manifest.json",json.dumps(manifest))
    target=tmp_path/"rejected-workspace"
    with pytest.raises(ValueError,match="模型"):
        backups.restore_bundle(bad,target)
    assert not target.exists()


def test_review_action_invalidates_backup_without_changing_dataset_truth(tmp_path,monkeypatch):
    _,database,_,_=fixture_bundle(tmp_path,monkeypatch)
    with sqlite3.connect(database) as connection:
        job_id=connection.execute("SELECT id FROM jobs WHERE job_type=?",(backups.JOB_TYPE,)).fetchone()[0]
        run_id=connection.execute("SELECT id FROM validation_runs").fetchone()[0]
        sid,digest=connection.execute("SELECT id,file_hash FROM samples LIMIT 1").fetchone()
        revision=connection.execute("SELECT revision FROM datasets LIMIT 1").fetchone()[0]
    before=backups._source_signature(database,job_id)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO validation_reviews(run_id,sample_id,sha256,state,updated_at) VALUES(?,?,?,'pending',CURRENT_TIMESTAMP)",(run_id,sid,digest))
        assert connection.execute("SELECT revision FROM datasets LIMIT 1").fetchone()[0]==revision
    assert backups._source_signature(database,job_id)!=before
