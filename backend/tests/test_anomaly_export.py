import csv
import hashlib
import io
import json
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from zipfile import ZipFile

import pytest
from sqlmodel import Session

from app.schemas.industrial import AnomalyExportRequest
from app.services import anomaly_export_service as exports, job_artifact_service, job_service
from app.services.directory_export_service import DirectoryExportPlanChangedError
from app.services.job_runner import JobCancelled, JobContext
from app.templates.anomaly_reader import package_rows
from app.templates import anomaly_reader
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


@pytest.mark.parametrize("delivery", ["zip", "directory"])
def test_export_reads_each_source_once_without_rereading_image_output(tmp_path: Path, monkeypatch, delivery):
    client, engine, dataset, plan, job = setup_export(tmp_path, monkeypatch, delivery)
    source_reads = {
        Path(sample["absolute_path"]): 0
        for sample in client.get(f"/api/datasets/{dataset['id']}/samples").json()["items"]
    }
    output_reads = []
    archive_reads = []
    artifact_reads = []
    original_open = Path.open
    original_archive_open = ZipFile.open

    def tracking_open(path, mode="r", *args, **kwargs):
        if "r" in mode:
            if path in source_reads:
                source_reads[path] += 1
            elif path.is_relative_to(tmp_path / "anomaly-exports") and path.suffix == ".png":
                output_reads.append(path)
            elif path.suffix == ".zip":
                artifact_reads.append(path)
        return original_open(path, mode, *args, **kwargs)

    def tracking_archive_open(archive, name, mode="r", *args, **kwargs):
        if mode == "r":
            archive_reads.append(name)
        return original_archive_open(archive, name, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    monkeypatch.setattr(ZipFile, "open", tracking_archive_open)
    result = exports.run_export(JobContext(job.id, engine, threading.Event()), job.parameters)

    assert set(source_reads.values()) == {1}
    assert output_reads == []
    assert archive_reads == []
    if delivery == "zip":
        assert len(artifact_reads) == 1
        path = artifact_reads[0]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == result["artifact"]["sha256"]
        with ZipFile(path) as archive:
            names = set(archive.namelist())
        assert {"samples.csv", "manifest.jsonl", "protocol.json", "export-report.json", "load_anomalib.py"} <= names
        assert len([name for name in names if name.endswith(".png")]) == result["exported_sample_count"]
    else:
        assert artifact_reads == []


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


def test_reader_checks_package_images_once_per_complete_read(tmp_path: Path, monkeypatch):
    _, engine, _, _, job = setup_export(tmp_path, monkeypatch, "directory")
    result = exports.run_export(JobContext(job.id, engine, threading.Event()), job.parameters)
    root = Path(result["output_path"])
    image_reads = {path: 0 for path in root.rglob("*.png")}
    original_open = Path.open

    def tracking_open(path, mode="r", *args, **kwargs):
        if "r" in mode and path in image_reads:
            image_reads[path] += 1
        return original_open(path, mode, *args, **kwargs)

    # Only the optional framework is substituted. The exported files, package
    # validation, and check_reader's split/label/batch checks run unchanged.
    class FrameworkDataModule:
        def __init__(self, **kwargs):
            assert kwargs["test_split_mode"] == "none"
            assert kwargs["val_split_mode"] == "from_dir"
            for split in ("train", "val", "test"):
                def batches(split=split):
                    samples = getattr(self, f"{split}_data").samples
                    return [SimpleNamespace(image_path=samples.image_path,
                                            gt_label=SimpleNamespace(tolist=lambda: samples.label_index))]
                setattr(self, f"{split}_dataloader", batches)

        def setup(self, stage):
            self._setup(stage)

    class FrameworkDataset:
        def __init__(self, *, samples, split, **kwargs):
            selected = [row for row in samples if row["split"] == split]
            self.samples = SimpleNamespace(image_path=[row["image_path"] for row in selected],
                                           label_index=[row["label_index"] for row in selected])

    for name, attrs in {
        "anomalib.data.datamodules.base.image": {"AnomalibDataModule": FrameworkDataModule},
        "anomalib.data.datasets.image.tabular": {"TabularDataset": FrameworkDataset},
        "torchvision.transforms.v2": {"Resize": lambda size: size},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(anomaly_reader, "version", lambda name: "2.7.0")
    monkeypatch.setattr(Path, "open", tracking_open)

    checked = anomaly_reader.check_reader(root)

    assert checked["split_preserved"] is True
    assert sum(checked["samples"].values()) == 16
    assert set(image_reads.values()) == {1}
