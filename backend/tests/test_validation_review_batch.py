import hashlib
import json
import threading
from collections import Counter
from pathlib import Path

from PIL import Image
import pytest
from sqlmodel import Session, select
from app.models.sample import Sample
from app.models.organization import DatasetBatch
from app.schemas.validation import ValidationRunCreate
from app.services import job_service, validation_run_service as runs
from app.services import anomaly_protocol_service as protocol
from app.services import industrial_plan_service as plans
from app.services.job_runner import JobContext
from test_validation_execution import workspace
from test_validation_results import completed_run


def scoped_batch_workspace(tmp_path, monkeypatch, image_count=56):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    parent, _old = completed_run(client, engine, dataset)
    response = client.post(f"/api/validation/runs/{parent.id}/freeze-threshold", json={"threshold": 2})
    assert response.status_code == 200, response.text
    folder = tmp_path / "scoped-batches"
    folder.mkdir()
    for index in range(image_count + 4):
        Image.new("RGB", (24, 24), (index, 21, 37)).save(folder / f"part-{index:03d}.png")
    target = client.post("/api/datasets", json={
        "name": "Two capture batches", "workflow_profile": "industrial_anomaly", "root_path": str(folder),
    }).json()
    response = client.post(f"/api/datasets/{target['id']}/scan", json={"folder_path": str(folder)})
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        wanted = DatasetBatch(dataset_id=target["id"], name="本次采集", code="wanted-batch")
        other = DatasetBatch(dataset_id=target["id"], name="另一次采集", code="other-batch")
        empty = DatasetBatch(dataset_id=target["id"], name="尚未采集", code="empty-batch")
        foreign = DatasetBatch(dataset_id=dataset["id"], name="其他项目批次", code="foreign-batch")
        session.add_all([wanted, other, empty, foreign])
        session.flush()
        batch_ids = {"wanted": wanted.id, "other": other.id, "empty": empty.id, "foreign": foreign.id}
        samples = session.exec(select(Sample).where(Sample.dataset_id == target["id"]).order_by(Sample.filename)).all()
        for index, sample in enumerate(samples):
            sample.capture_group_id = f"independent-{index}"
            batch = wanted if index < image_count else other if index < image_count + 2 else None
            sample.batch_id = batch.id if batch else None
            sample.capture_batch_id = batch.code if batch else None
            session.add(sample)
        expected = [sample.id for sample in samples[:image_count]]
        session.commit()
    return client, engine, parent, target, batch_ids, expected


def test_batch_scope_is_frozen_and_full_preview_is_paginated(tmp_path, monkeypatch):
    client, engine, parent, target, batch_ids, expected = scoped_batch_workspace(tmp_path, monkeypatch)
    endpoint = f"/api/validation/runs/{parent.id}/batch-previews"
    response = client.post(endpoint, json={
        "target_dataset_id": target["id"], "batch_scope": "batch", "batch_id": batch_ids["wanted"],
    })
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["total"] == 56 and len(plan["rows"]) == 50
    assert plan["summary"]["included_count"] == 56
    assert plan["summary"]["scope_label"] == "采集批次「本次采集」"
    plan_url = f"/api/datasets/{target['id']}/industrial/plans/{plan['plan_id']}"
    second = client.get(plan_url, params={"page": 2}).json()
    assert second["plan_hash"] == plan["plan_hash"] and second["page"] == 2
    assert {row["sample_id"] for row in plan["rows"] + second["rows"]} == set(expected)
    assert len(second["rows"]) == 6
    with Session(engine) as session:
        run = runs.create_run(session, target["id"], ValidationRunCreate(
            plan_id=plan["plan_id"], plan_hash=plan["plan_hash"]))
        contract = runs.read_contract(runs.get_run(session, run.id))
        assert contract["batch_scope"] == {"mode": "batch", "batch_id": batch_ids["wanted"], "sample_ids": None}
        assert {row["sample_id"] for row in contract["rows"] if row["split"]} == set(expected)
    assert client.patch(f"/api/datasets/{target['id']}", json={"notes": "changed after preview"}).status_code == 200
    assert client.get(plan_url, params={"page": 2}).status_code == 409
    response = client.post(f"/api/datasets/{target['id']}/validation/runs", json={
        "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
    })
    assert response.status_code == 409
    with Session(engine) as session:
        assert {row["sample_id"] for row in runs.read_contract(runs.get_run(session, run.id))["rows"]} == set(expected)


@pytest.mark.parametrize("scope,expected_count", [("all", 8), ("unassigned", 2)])
def test_batch_scope_supports_all_and_unassigned(tmp_path, monkeypatch, scope, expected_count):
    client, _engine, parent, target, _batches, _ids = scoped_batch_workspace(tmp_path, monkeypatch, image_count=4)
    response = client.post(f"/api/validation/runs/{parent.id}/batch-previews", json={
        "target_dataset_id": target["id"], "batch_scope": scope,
    })
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["included_count"] == expected_count
    assert response.json()["total"] == expected_count


def test_batch_scope_rejects_foreign_and_empty_batches_and_intersects_sample_ids(tmp_path, monkeypatch):
    client, _engine, parent, target, batches, expected = scoped_batch_workspace(tmp_path, monkeypatch, image_count=4)
    endpoint = f"/api/validation/runs/{parent.id}/batch-previews"
    payload = {"target_dataset_id": target["id"], "batch_scope": "batch", "batch_id": batches["foreign"]}
    response = client.post(endpoint, json=payload)
    assert response.status_code == 422 and "不属于" in response.json()["detail"]
    response = client.post(endpoint, json={**payload, "batch_id": batches["empty"]})
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["blocked"] and response.json()["total"] == 0
    assert "没有登记图片" in response.json()["summary"]["blockers"][0]
    response = client.post(endpoint, json={
        **payload, "batch_id": batches["wanted"], "sample_ids": expected[:2],
    })
    assert response.status_code == 200, response.text
    assert {row["sample_id"] for row in response.json()["rows"]} == set(expected[:2])
    assert client.post(endpoint, json={**payload, "batch_id": None}).status_code == 422
    assert client.post(endpoint, json={**payload, "batch_scope": "all"}).status_code == 422


def test_batch_scope_excludes_full_component_when_content_is_outside_batch(tmp_path, monkeypatch):
    client, engine, parent, target, batches, expected = scoped_batch_workspace(tmp_path, monkeypatch, image_count=4)
    with Session(engine) as session:
        samples = session.exec(select(Sample).where(Sample.dataset_id == target["id"]).order_by(Sample.filename)).all()
        Path(samples[4].absolute_path).write_bytes(Path(samples[0].absolute_path).read_bytes())
        samples[4].file_hash = samples[0].file_hash
        session.add(samples[4])
        session.commit()
    response = client.post(f"/api/validation/runs/{parent.id}/batch-previews", json={
        "target_dataset_id": target["id"], "batch_scope": "batch", "batch_id": batches["wanted"],
    })
    assert response.status_code == 200, response.text
    plan = response.json()
    assert {row["sample_id"] for row in plan["rows"]} == set(expected)
    assert plan["summary"]["included_count"] == 3
    assert plan["rows"][0]["split"] is None and "范围外" in plan["rows"][0]["exclusion_reason"]


def test_legacy_batch_preview_keeps_its_frozen_rows_without_scope_metadata(tmp_path, monkeypatch):
    client, engine, parent, target, _batches, _expected = scoped_batch_workspace(tmp_path, monkeypatch, image_count=4)
    response = client.post(f"/api/validation/runs/{parent.id}/batch-previews", json={"target_dataset_id": target["id"]})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["summary"]["included_count"] == 8
    with Session(engine) as session:
        source = plans.load(session, target["id"], preview["plan_id"])
        summary = {key: value for key, value in source["summary"].items() if key not in {"scope_label", "selected_count"}}
        old_plan = plans.freeze("validation", target["id"], source["dataset_revision"], source["rows"], summary,
            mode="batch", recipe=source["recipe"], parent_run_id=source["parent_run_id"],
            parent_model_sha256=source["parent_model_sha256"], parent_threshold=source["parent_threshold"],
            triage_policy=source["triage_policy"])
        run = runs.create_run(session, target["id"], ValidationRunCreate(
            plan_id=old_plan["plan_id"], plan_hash=old_plan["plan_hash"]))
        contract = runs.read_contract(runs.get_run(session, run.id))
        assert "batch_scope" not in contract
        assert contract["rows"] == source["rows"]


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


def test_batch_excludes_conflicting_truth_for_identical_content(tmp_path, monkeypatch):
    client,engine,dataset=workspace(tmp_path,monkeypatch)
    parent,old=completed_run(client,engine,dataset)
    base=f"/api/validation/runs/{parent.id}"
    client.post(base+"/freeze-threshold",json={"threshold":2})
    target=new_batch(client,engine,tmp_path,old)
    with Session(engine) as session:
        samples=session.exec(select(Sample).where(Sample.dataset_id==target["id"]).order_by(Sample.filename)).all()
        left,right=samples[2:4]
        Path(right.absolute_path).write_bytes(Path(left.absolute_path).read_bytes())
        right.file_hash=left.file_hash
        for sample,status in [(left,"ok"),(right,"ng")]:
            sample.triage_status=status;sample.ok_grade="clear" if status=="ok" else None
            sample.triaged_file_hash=sample.file_hash;sample.triage_policy_version=1;session.add(sample)
        session.commit()
    plan=client.post(base+"/batch-previews",json={"target_dataset_id":target["id"]}).json()
    assert plan["summary"]["included_count"]==2
    assert sum("判定矛盾" in (r["exclusion_reason"] or "") for r in plan["rows"])==2


@pytest.mark.parametrize("truth", ["known", "unknown", "changed"])
def test_batch_checks_each_source_content_once(tmp_path, monkeypatch, truth):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    parent, old = completed_run(client, engine, dataset)
    base = f"/api/validation/runs/{parent.id}"
    assert client.post(base + "/freeze-threshold", json={"threshold": 2}).status_code == 200
    target = new_batch(client, engine, tmp_path, old)
    with Session(engine) as session:
        samples = session.exec(select(Sample).where(Sample.dataset_id == target["id"]).order_by(Sample.filename)).all()
        paths = {Path(sample.absolute_path) for sample in samples}
        if truth != "unknown":
            for sample in samples:
                sample.triage_status = "ok"
                sample.ok_grade = "clear"
                sample.triaged_file_hash = sample.file_hash
                sample.triage_policy_version = 1
                session.add(sample)
            session.commit()
        if truth == "changed":
            Image.new("RGB", (24, 24), "red").save(samples[2].absolute_path)
    reads = Counter()
    original_digest = protocol.file_digest
    def count_source_digests(path):
        if path in paths:
            reads[path] += 1
        return original_digest(path)
    monkeypatch.setattr(protocol, "file_digest", count_source_digests)
    response = client.post(base + "/batch-previews", json={"target_dataset_id": target["id"]})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert reads == Counter({path: 1 for path in paths})
    assert plan["summary"]["included_count"] == (2 if truth == "changed" else 4)
    assert plan["summary"]["unknown_count"] == (4 if truth == "unknown" else 0)
    if truth == "changed":
        assert sum("原图不可用或内容变化" in (row["exclusion_reason"] or "") for row in plan["rows"]) == 2
