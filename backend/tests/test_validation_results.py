import hashlib
import json
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models.sample import Sample
from app.schemas.validation import ValidationRunCreate
from app.services import industrial_plan_service as plans, job_service
from app.services import validation_result_service as results, validation_run_service as runs
from test_validation_execution import workspace


def completed_run(client, engine, dataset):
    plan = client.post(f"/api/datasets/{dataset['id']}/validation/previews", json={}).json()
    with Session(engine) as session:
        run = runs.create_run(session, dataset["id"], ValidationRunCreate(plan_id=plan["plan_id"], plan_hash=plan["plan_hash"]))
        job_service.transition_job(session, run.job.id, "running")
        contract = runs.read_contract(runs.get_run(session, run.id))
        root = runs.run_root(run.id) / f"attempt-{run.job.id}"
        root.mkdir()
        from PIL import Image
        for row in contract["rows"]:
            if row["split"]:
                for directory, extension in (("previews", "jpg"), ("heatmaps", "png")):
                    (root / directory).mkdir(exist_ok=True)
                    Image.new("RGB", (16, 16)).save(root / directory / f"{row['sample_id']}.{extension}")
        predictions = [dict(sample_id=r["sample_id"], score=float(r["sample_id"] % 5)) for r in contract["rows"] if r["split"]]
        payload = dict(predictions=predictions, map_scale=10, total_seconds=2, fit_seconds=1, model_sha256="a" * 64)
        (root / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        digest = hashlib.sha256((root / "result.json").read_bytes()).hexdigest()
        job_service.transition_job(session, run.job.id, "succeeded", result=dict(artifact_job_id=run.job.id, result_sha256=digest))
    return run, contract


def test_metrics_ties_unknown_and_no_abnormal():
    rows = [dict(label_index=0, score=1), dict(label_index=1, score=1), dict(label_index=None, score=100)]
    value = results.metrics(rows, 1)
    assert value["auroc"] == 0.5 and value["unknown"] == 1
    assert value["false_positive"] == value["true_positive"] == 1
    normal_only = results.metrics(rows[:1], 2)
    assert normal_only["recall"] is None and normal_only["auroc"] is None


def test_threshold_selection_never_uses_hidden_test():
    rows = [dict(split="val", label_index=0, score=2), dict(split="val", label_index=1, score=3)]
    expected = results.recommended_threshold(rows)
    assert results.recommended_threshold(rows + [dict(split="test", label_index=1, score=-10000)]) == expected


def test_test_lock_frozen_report_and_truth_history(tmp_path: Path, monkeypatch):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    run, contract = completed_run(client, engine, dataset)
    base = f"/api/validation/runs/{run.id}"
    test = next(r for r in contract["rows"] if r["split"] == "test")
    assert client.get(base + "/predictions", params={"split": "test"}).status_code == 409
    assert client.get(base + f"/images/{test['sample_id']}").status_code == 409
    report = client.get(base + "/report").json()
    assert not any(r["split"] == "test" for r in report["predictions"])
    assert report["run"]["test_locked"]
    frozen = client.post(base + "/freeze-threshold", json={"threshold": 2}).json()
    assert frozen["independent_test"]
    assert client.post(base + "/freeze-threshold", json={"threshold": 2}).json() == frozen
    assert client.post(base + "/freeze-threshold", json={"threshold": 3}).status_code == 409
    assert client.get(base + "/predictions", params={"split": "test", "threshold": 3}).status_code == 422
    assert client.get(base + "/images/" + str(test["sample_id"])).status_code == 200
    assert client.get(base + "/results", params={"threshold": 100}).json()["frozen_decision"] == frozen
    page = client.get(base + "/predictions", params={"category": "truth_normal", "threshold": -1}).json()
    assert page["total"] == client.get(base + "/results").json()["validation_metrics"]["normal"]
    row = page["items"][0]
    with Session(engine) as session:
        sample = session.get(Sample, row["sample_id"])
        sample.triage_status = "ng"; session.add(sample); session.commit()
    after = client.get(base + "/predictions", params={"category": "truth_normal"}).json()
    assert any(r["judgment_changed"] for r in after["items"])
    assert client.get(base + "/results").json()["frozen_decision"] == frozen
    second, _ = completed_run(client, engine, dataset)
    reused = client.post(f"/api/validation/runs/{second.id}/freeze-threshold", json={"threshold": 2}).json()
    assert reused["reused_test_hashes"] > 0 and not reused["independent_test"]
