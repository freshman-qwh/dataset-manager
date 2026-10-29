import csv
import io
import json
import threading
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlmodel import Session

from app.schemas.industrial import AnomalyExportRequest
from app.services import anomaly_export_service as exports, job_artifact_service, job_service
from app.services.directory_export_service import DirectoryExportPlanChangedError
from app.services.job_runner import JobCancelled, JobContext
from app.templates.anomaly_reader import package_rows
from test_anomaly_protocol import protocol
from test_capture_groups import example


def setup_export(tmp_path, monkeypatch, delivery="zip"):
    client, engine, dataset = example(tmp_path, monkeypatch)
    from app.core.config import get_settings
    settings = get_settings().model_copy(update={"storage_root": tmp_path})
    monkeypatch.setattr(exports, "get_settings", lambda: settings)
    monkeypatch.setattr(job_artifact_service, "job_artifact_root", lambda: tmp_path / "artifacts")
    plan = protocol(client, dataset["id"])
    payload = AnomalyExportRequest(plan_id=plan["plan_id"], plan_hash=plan["plan_hash"], delivery=delivery)
    with Session(engine) as session:
        job = exports.create_job(session, dataset["id"], payload).job
        job = job_service.transition_job(session, job.id, "running")
    return client, engine, dataset, plan, job


@pytest.mark.parametrize("delivery", ["zip", "directory"])
def test_export_reads_all_sets_and_preserves_source(tmp_path: Path, monkeypatch, delivery):
    client, engine, dataset, plan, job = setup_export(tmp_path, monkeypatch, delivery)
    parameters = job.parameters
    assert len(json.dumps(parameters)) < 500
    context = JobContext(job.id, engine, threading.Event())
    result = exports.run_export(context, parameters)
    if delivery == "zip":
        path = job_artifact_service.resolve_job_artifact(tmp_path / "artifacts", job_id=job.id, filename=result["artifact"]["filename"])
        root = tmp_path / "中文 空格" / "移动后的数据包"
        with ZipFile(path) as archive:
            archive.extractall(root)
    else:
        root = Path(result["output_path"])
    rows = package_rows(root)
    assert len(rows) == 16
    assert not list(root.rglob("*mask*"))
    assert (root / "load_anomalib.py").is_file()
    assert (root / "requirements-reader-lock-windows.txt").is_file()
    protocol_doc = json.loads((root / "protocol.json").read_text(encoding="utf-8"))
    assert protocol_doc["independent_validation"]
    assert protocol_doc["triage_policy"]["version"] == 1
    assert all(s["split"] is None for s in client.get(f"/api/datasets/{dataset['id']}/samples").json()["items"])


def test_job_creation_reuses_active_and_refuses_stale(tmp_path: Path, monkeypatch):
    client, engine, dataset, plan, job = setup_export(tmp_path, monkeypatch)
    payload = {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]}
    response = client.post(f"/api/datasets/{dataset['id']}/industrial/export-jobs", json=payload)
    assert response.json()["job"]["id"] == job.id
    assert response.json()["created"] is False
    client.patch(f"/api/datasets/{dataset['id']}", json={"notes": "changed"})
    assert client.post(f"/api/datasets/{dataset['id']}/industrial/export-jobs", json=payload).status_code == 409
    with pytest.raises(Exception, match="预览已过期"):
        exports.run_export(JobContext(job.id, engine, threading.Event()), job.parameters)


@pytest.mark.parametrize("delivery", ["zip", "directory"])
@pytest.mark.parametrize("failure", ["source", "space", "cancel"])
def test_failed_export_never_publishes_partial_output(tmp_path: Path, monkeypatch, delivery, failure):
    client, engine, dataset, plan, job = setup_export(tmp_path, monkeypatch, delivery)
    if failure == "source":
        path = client.get(f"/api/datasets/{dataset['id']}/samples").json()["items"][0]["absolute_path"]
        Path(path).write_bytes(b"changed after preview")
    else:
        def interrupted(source, output, **kwargs):
            output.write(b"partial output")
            if failure == "cancel":
                raise JobCancelled("Cancellation requested during copy")
            raise OSError("No space left on device")
        monkeypatch.setattr(exports, "_copy_verified", interrupted)
    expected_error = {"source": DirectoryExportPlanChangedError, "space": OSError, "cancel": JobCancelled}[failure]
    with pytest.raises(expected_error):
        exports.run_export(JobContext(job.id, engine, threading.Event()), job.parameters)
    assert not list((tmp_path / "artifacts").rglob("*.zip"))
    assert not list((tmp_path / "artifacts").rglob("*.part"))
    assert not list((tmp_path / "anomaly-exports").glob("*"))


def test_reader_dependency_templates_match_verified_lock():
    backend = Path(__file__).resolve().parents[1]
    for name in ("reader-requirements.txt", "reader-requirements-lock-windows.txt"):
        assert (backend / name).read_bytes() == (exports.TEMPLATE_ROOT / name).read_bytes()
