import hashlib
import json
import sys
import threading
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image
from sqlmodel import Session
from app.schemas.validation import RuntimeRead, ValidationRunCreate
from app.services import job_service, validation_plan_service, validation_run_service as runs, validation_runtime_service as runtime
from app.services.job_runner import JobCancelled, JobContext
from app.services.validation_process_service import run_process
from test_capture_groups import example


def workspace(tmp_path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    from app.core.config import get_settings
    settings = get_settings().model_copy(update={"storage_root": tmp_path})
    monkeypatch.setattr(runs, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "status", lambda *args: RuntimeRead(ready=True, python_path=sys.executable, message="test runtime"))
    return client, engine, dataset


def test_exploration_is_normal_only_and_strict_preview_retains_test(tmp_path: Path, monkeypatch):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    endpoint = f"/api/datasets/{dataset['id']}/validation/previews"
    explore = client.post(endpoint, json={"mode": "exploration"}).json()
    assert not explore["summary"]["blocked"]
    assert explore["summary"]["counts"]["test"] == {"normal": 0, "abnormal": 0}
    assert all(row["label_index"] == 0 for row in explore["rows"] if row["split"])
    evaluation = client.post(endpoint, json={"mode": "evaluation"}).json()
    assert not evaluation["summary"]["blocked"]
    assert evaluation["summary"]["counts"]["test"]["abnormal"] > 0
    assert client.get(f"/api/datasets/{dataset['id']}").json()["revision"] == dataset["revision"]


@pytest.mark.parametrize("failure", [None, "cancel", "missing", "source"])
def test_worker_publication_and_failure_are_atomic(tmp_path: Path, monkeypatch, failure):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    plan = client.post(f"/api/datasets/{dataset['id']}/validation/previews", json={}).json()
    with Session(engine) as session:
        run = runs.create_run(session, dataset["id"], ValidationRunCreate(plan_id=plan["plan_id"], plan_hash=plan["plan_hash"]))
        job = job_service.transition_job(session, run.job.id, "running")
    before = {row["source_absolute_path"]: row["sha256"] for row in plan["rows"]}
    source_reads = Counter()
    original_open = Path.open
    def count_source_reads(path, mode="r", *args, **kwargs):
        if str(path) in before and mode == "rb":
            source_reads[str(path)] += 1
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", count_source_reads)
    def worker(command, log, checkpoint, **kwargs):
        root = Path(command[-1])
        request = json.loads((root / "input.json").read_text(encoding="utf-8"))
        assert all((root / row["image_path"]).is_file() for row in request["rows"])
        if failure == "cancel": raise JobCancelled("cancel during worker")
        for row in request["rows"]:
            for directory, ext in (("previews", "jpg"), ("heatmaps", "png")):
                (root / directory).mkdir(exist_ok=True)
                Image.new("RGB", (8, 8), "white").save(root / directory / f"{row['sample_id']}.{ext}")
        (root / "model.pt").write_bytes(b"owned model state")
        predictions = [dict(sample_id=r["sample_id"], score=float(r["sample_id"])) for r in request["rows"]]
        if failure == "missing": predictions.pop()
        if failure == "source": Path(request["rows"][-1]["source_absolute_path"]).write_bytes(b"changed")
        (root / "result.json").write_text(json.dumps(dict(anomalib="2.7.0", recipe=request["recipe"], predictions=predictions,
            model_sha256=hashlib.sha256(b"owned model state").hexdigest())), encoding="utf-8")
    monkeypatch.setattr(runs, "run_process", worker)
    if failure in {"cancel", "missing"}:
        with pytest.raises((JobCancelled, ValueError)):
            runs.execute(JobContext(job.id, engine, threading.Event()), job.parameters)
        assert not (runs.run_root(run.id) / f"attempt-{job.id}").exists()
    else:
        result = runs.execute(JobContext(job.id, engine, threading.Event()), job.parameters)
        assert result["sample_count"] == 16
        assert not (runs.run_root(run.id) / f"attempt-{job.id}" / "images").exists()
    # Images are verified while copying the frozen inputs. Later changes in the
    # original folder must not invalidate results computed from those copies.
    assert source_reads == Counter({path: 1 for path in before})
    assert not list(runs.run_root(run.id).glob("*.part"))
    if failure != "source":
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())


def test_changed_source_is_rejected_before_frozen_copy(tmp_path: Path, monkeypatch):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    plan = client.post(f"/api/datasets/{dataset['id']}/validation/previews", json={}).json()
    with Session(engine) as session:
        run = runs.create_run(session, dataset["id"], ValidationRunCreate(plan_id=plan["plan_id"], plan_hash=plan["plan_hash"]))
        job = job_service.transition_job(session, run.job.id, "running")
    Path(plan["rows"][0]["source_absolute_path"]).write_bytes(b"changed after preview")
    worker_calls = []
    monkeypatch.setattr(runs, "run_process", lambda *args, **kwargs: worker_calls.append(args))
    with pytest.raises(ValueError, match="源文件内容在预检后发生变化"):
        runs.execute(JobContext(job.id, engine, threading.Event()), job.parameters)
    assert worker_calls == []
    assert not (runs.run_root(run.id) / f"attempt-{job.id}").exists()
    assert not list(runs.run_root(run.id).glob("*.part"))


def test_child_process_cancellation_stops_waiting(tmp_path: Path):
    ticks = 0
    def cancel():
        nonlocal ticks
        ticks += 1
        if ticks >= 3: raise JobCancelled("requested")
    with pytest.raises(JobCancelled):
        run_process([sys.executable, "-I", "-c", "import time; time.sleep(30)"], tmp_path / "worker.log", cancel)
    assert ticks == 3


def test_invalid_runtime_has_actionable_message(tmp_path: Path):
    status = runtime.probe(str(tmp_path / "missing-python.exe"))
    assert not status.ready
    assert "找不到" in status.message
