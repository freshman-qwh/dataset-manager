import hashlib
import json
import threading
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select
from app.models.sample import Sample
from app.schemas.validation import ValidationRunCreate
from app.services import job_service, validation_run_service as runs
from app.services.job_runner import JobContext
from test_validation_execution import workspace
from test_validation_results import completed_run


def new_batch(client, engine, tmp_path, old):
    folder = tmp_path / "new-batch"; folder.mkdir()
    for i in range(6):
        Image.new("RGB", (24, 24), (60+i*10, 70, 80)).save(folder / f"part-{i}.png")
    (folder / "part-0.png").write_bytes(Path(old["rows"][0]["source_absolute_path"]).read_bytes())
    dataset = client.post("/api/datasets", json={"name": "new", "workflow_profile": "industrial_anomaly", "root_path": str(folder)}).json()
    response = client.post(f"/api/datasets/{dataset['id']}/scan", json={"folder_path": str(folder)})
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        for i, sample in enumerate(session.exec(select(Sample).where(Sample.dataset_id == dataset["id"]).order_by(Sample.filename)).all()):
            sample.capture_group_id = f"new-{i//2}"; sample.capture_batch_id = "new-batch"
            session.add(sample)
        session.commit()
    return dataset


def test_review_is_explicit_bounded_and_version_checked(tmp_path, monkeypatch):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    run, contract = completed_run(client, engine, dataset)
    base = f"/api/validation/runs/{run.id}"
    sid = next(r["sample_id"] for r in contract["rows"] if r["split"] == "val")
    tid = next(r["sample_id"] for r in contract["rows"] if r["split"] == "test")
    assert client.post(base+"/review", json={"sample_ids": [sid, tid]}).status_code == 409
    assert client.get(base+"/review").json()["pending"] == 0
    before = client.get(f"/api/samples/{sid}/triage").json()
    assert client.post(base+"/review", json={"sample_ids": [sid]}).json()["pending"] == 1
    nav = f"/api/datasets/{dataset['id']}/triage/navigation"
    assert client.get(nav, params={"review_run":run.id}).json()["total"] == 1
    assert client.get(f"/api/samples/{sid}/triage").json() == before
    payload = dict(state="reviewed", expected_version=before["triage_version"]+1, expected_file_hash=before["file_hash"])
    assert client.patch(base+f"/review/{sid}", json=payload).status_code == 409
    payload["expected_version"] = before["triage_version"]
    assert client.patch(base+f"/review/{sid}", json=payload).json()["reviewed"] == 1
    assert client.get(nav, params={"review_run":run.id}).json()["total"] == 0
    assert client.post(base+"/review", json={"sample_ids": [sid]}).json()["pending"] == 1
    assert client.delete(f"/api/samples/{sid}").status_code == 200
    assert client.get(base+"/review").json()["pending"] == 0


def test_batch_freezes_original_model_and_excludes_transitive_overlap(tmp_path, monkeypatch):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    parent, old = completed_run(client, engine, dataset)
    base = f"/api/validation/runs/{parent.id}"
    target = new_batch(client, engine, tmp_path, old)
    assert client.post(base+"/batch-previews", json={"target_dataset_id": target["id"]}).status_code == 409
    client.post(base+"/freeze-threshold", json={"threshold":2})
    plan = client.post(base+"/batch-previews", json={"target_dataset_id": target["id"]}).json()
    assert plan["summary"]["included_count"] == 4 and plan["summary"]["excluded_count"] == 2
    assert plan["summary"]["unknown_count"] == 4
    with Session(engine) as session:
        run = runs.create_run(session, target["id"], ValidationRunCreate(plan_id=plan["plan_id"],plan_hash=plan["plan_hash"]))
        assert run.parent_run_id == parent.id and run.mode == "batch"
        job = job_service.transition_job(session, run.job.id,"running")
    def worker(command, log, checkpoint, **kwargs):
        root = Path(command[-1]); request = json.loads((root/"input.json").read_text(encoding="utf-8"))
        assert request["parent_model"]["sha256"] == hashlib.sha256(b"frozen model").hexdigest()
        for row in request["rows"]:
            assert row["split"] == "batch"
            for directory, extension in (("previews","jpg"),("heatmaps","png")):
                (root/directory).mkdir(exist_ok=True); Image.new("RGB",(8,8)).save(root/directory/f"{row['sample_id']}.{extension}")
        (root/"result.json").write_text(json.dumps(dict(anomalib="2.7.0",recipe=request["recipe"],
            predictions=[dict(sample_id=r["sample_id"],score=3) for r in request["rows"]],
            model_sha256=request["parent_model"]["sha256"], map_scale=10,fit_seconds=0,total_seconds=1)))
    monkeypatch.setattr(runs,"run_process",worker)
    result = runs.execute(JobContext(job.id,engine,threading.Event()),job.parameters)
    with Session(engine) as session:
        job_service.transition_job(session,job.id,"succeeded",result=result)
    child = f"/api/validation/runs/{run.id}"
    summary = client.get(child+"/results").json()
    assert summary["threshold"] == 2 and summary["fit_seconds"] == 0
    assert summary["validation_metrics"]["unknown"] == 4 and summary["validation_metrics"]["recall"] is None
    assert summary["reference_run_id"] == parent.id
    assert client.get(child+"/results",params={"threshold":1}).status_code == 422
    assert client.post(child+"/freeze-threshold",json={"threshold":2}).status_code == 409
    assert client.delete(base).status_code == 409
    assert client.delete(child).status_code == 204
    assert client.delete(base).status_code == 204
    # Deleting results does not reset test-content exposure history.
    another,_ = completed_run(client,engine,dataset)
    assert not client.post(f"/api/validation/runs/{another.id}/freeze-threshold",json={"threshold":2}).json()["independent_test"]
