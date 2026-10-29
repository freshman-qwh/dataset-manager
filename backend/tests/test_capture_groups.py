import hashlib
import json
from pathlib import Path

from sqlmodel import Session, select

from app.models.dataset_snapshot import DatasetSnapshot
from app.models.sample import Sample
from app.services import industrial_example_service, industrial_plan_service as plans, dataset_snapshot_service as snapshots
from test_dataset_snapshots import make_client


def example(tmp_path, monkeypatch):
    from app.core.config import get_settings
    settings = get_settings().model_copy(update={"storage_root": tmp_path})
    monkeypatch.setattr(industrial_example_service, "get_settings", lambda: settings)
    monkeypatch.setattr(plans, "get_settings", lambda: settings)
    client, engine = make_client(tmp_path / "snapshots", monkeypatch)
    dataset = client.post("/api/datasets/industrial-example").json()
    return client, engine, dataset


def test_group_preview_atomic_confirmation_retry_and_filters(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    did = dataset["id"]
    base = f"/api/datasets/{did}"
    samples = client.get(f"{base}/samples").json()["items"]
    ids = [samples[0]["id"], samples[1]["id"]]
    raw_hashes = {s["absolute_path"]: hashlib.sha256(Path(s["absolute_path"]).read_bytes()).hexdigest() for s in samples}
    plan = client.post(f"{base}/industrial/group-previews", json={"sample_ids": ids, "capture_group_id": "new-part", "capture_batch_id": "batch"}).json()
    assert client.get(base).json()["revision"] == dataset["revision"]
    body = {"plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"]}
    bad = client.post(f"{base}/industrial/group-previews/{plan['plan_id']}/confirm", json={**body, "confirmation": "wrong"})
    assert bad.status_code == 409
    response = client.post(f"{base}/industrial/group-previews/{plan['plan_id']}/confirm", json=body)
    assert response.status_code == 200, response.text
    again = client.post(f"{base}/industrial/group-previews/{plan['plan_id']}/confirm", json=body)
    assert again.json() == response.json()
    filtered = client.get(f"{base}/samples", params={"capture_group_id": "new-part", "capture_batch_id": "batch"}).json()
    assert filtered["total"] == 2
    assert all(s["split"] is None for s in filtered["items"])
    manifest = client.get(f"{base}/export-manifest", params={"capture_group_id": "new-part"}).json()
    assert manifest["exported_sample_count"] == 2
    snapshot = client.post(f"{base}/snapshots", json={"sample_query": {"capture_group_id": "new-part"}}).json()
    assert snapshot["sample_count"] == 2
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha for path, sha in raw_hashes.items())


def test_group_mapping_exact_paths_and_stale_rejection(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    base = f"/api/datasets/{dataset['id']}"
    sample = client.get(f"{base}/samples").json()["items"][0]
    mapping = json.dumps([{"path": sample["relative_path"], "part": "P1"}])
    payload = {"mode": "mapping", "mapping_text": mapping, "path_column": "path", "group_column": "part"}
    plan = client.post(f"{base}/industrial/group-previews", json=payload).json()
    assert plan["total"] == 1
    client.patch(base, json={"notes": "changed"})
    rejected = client.post(f"{base}/industrial/group-previews/{plan['plan_id']}/confirm", json={"plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"]})
    assert rejected.status_code == 409
    payload["mapping_text"] = json.dumps([{"path": "not/existing.png", "part": "P1"}])
    assert client.post(f"{base}/industrial/group-previews", json=payload).status_code == 422


def test_snapshot_v2_tracks_triage_and_groups_and_reads_v1(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    did = dataset["id"]
    base = f"/api/datasets/{did}"
    first = client.post(f"{base}/snapshots", json={"name": "before"}).json()
    with Session(engine) as session:
        sample = session.exec(select(Sample).where(Sample.dataset_id == did)).first()
        sample.triage_status = "ng"
        sample.capture_group_id = "changed"
        session.add(sample)
        session.commit()
    second = client.post(f"{base}/snapshots", json={"name": "after"}).json()
    from app.services.dataset_snapshot_compare_service import compare_snapshots
    with Session(engine) as session:
        result = compare_snapshots(session, did, first["id"], second["id"])
        assert result.summary.metadata_changed == 1
        # Model defaults must not invalidate an original v1 document's hash.
        record = session.get(DatasetSnapshot, first["id"])
        path = snapshots.snapshot_artifact_path(session, did, first["id"])
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["content"]["schema_version"] = 1
        raw["content"].pop("defect_type_catalog")
        for row in raw["content"]["samples"]:
            for key in list(row):
                if key.startswith(("triage", "triaged", "capture_", "defect_", "primary_defect")) or key == "ok_grade":
                    row.pop(key)
        sha = plans.digest(raw["content"])
        raw["content_sha256"] = sha
        record.content_sha256 = sha
        session.add(record)
        session.commit()
        path.write_text(json.dumps(raw), encoding="utf-8")
        result = compare_snapshots(session, did, first["id"], second["id"])
        assert result.comparison_notes
        assert result.summary.metadata_changed == 0
