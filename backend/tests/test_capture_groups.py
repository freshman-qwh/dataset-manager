import hashlib
import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.models.dataset_snapshot import DatasetSnapshot
from app.models.organization import DatasetBatch
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


def test_filename_group_preview_with_sample_ids_ignores_out_of_scope_names(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    with Session(engine) as session:
        samples = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"]).order_by(Sample.id)).all()
        selected_id = samples[0].id
        for sample in samples[1:]:
            sample.relative_path = f"unrelated-{sample.id}.png"
        session.commit()
    endpoint = f"/api/datasets/{dataset['id']}/industrial/group-previews"
    response = client.post(endpoint, json={"mode": "filename", "sample_ids": [selected_id]})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["total"] == 1
    assert plan["rows"][0]["sample_id"] == selected_id


@pytest.mark.parametrize("mode", ["selected", "filename", "directories", "mapping"])
@pytest.mark.parametrize("scope", ["selected", "batch"])
def test_group_range_applies_consistently_and_keeps_outside_rows(tmp_path: Path, monkeypatch, mode, scope):
    client, engine, dataset = example(tmp_path, monkeypatch)
    with Session(engine) as session:
        samples = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"]).order_by(Sample.id)).all()
        selected_ids = [sample.id for sample in samples[:2]]
        paths = [f"part/part_001_cam{index}.png" for index in range(2)]
        for index, sample in enumerate(samples):
            sample.relative_path = paths[index] if index < 2 else f"unmatched-{sample.id}.png"
            sample.capture_batch_id = "target-batch" if index < 2 else "other-batch"
        session.commit()
        previous = {sample.id: sample.model_dump() for sample in samples}
        source_hashes = {sample.absolute_path: hashlib.sha256(Path(sample.absolute_path).read_bytes()).hexdigest() for sample in samples}
    payload = {"mode": mode, "scope": scope}
    if scope == "selected":
        payload["sample_ids"] = selected_ids
    else:
        payload["scope_capture_batch_id"] = "target-batch"
    if mode == "selected":
        payload["capture_group_id"] = "shared-part"
    elif mode == "mapping":
        payload["mapping_text"] = json.dumps([{"relative_path": path, "capture_group_id": "mapped-part"} for path in paths])
    endpoint = f"/api/datasets/{dataset['id']}/industrial/group-previews"
    response = client.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["summary"]["scope"] == scope
    assert plan["summary"]["scope_sample_count"] == plan["total"] == 2
    assert {row["sample_id"] for row in plan["rows"]} == set(selected_ids)
    frozen = client.get(f"/api/datasets/{dataset['id']}/industrial/plans/{plan['plan_id']}").json()
    assert frozen["summary"] == plan["summary"]
    assert client.get(f"/api/datasets/{dataset['id']}").json()["revision"] == dataset["revision"]
    result = client.post(f"{endpoint}/{plan['plan_id']}/confirm", json={
        "plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"],
    })
    assert result.status_code == 200, result.text
    expected_group = {"selected": "shared-part", "filename": "part_001", "directories": "part", "mapping": "mapped-part"}[mode]
    with Session(engine) as session:
        current = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"])).all()
        for sample in current:
            if sample.id in selected_ids:
                assert sample.capture_group_id == expected_group
                assert sample.capture_batch_id == previous[sample.id]["capture_batch_id"]
                assert sample.triage_status == previous[sample.id]["triage_status"]
                assert sample.split == previous[sample.id]["split"]
            else:
                assert sample.model_dump() == previous[sample.id]
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected for path, expected in source_hashes.items())


@pytest.mark.parametrize("scope", ["selected", "batch"])
def test_group_mapping_rejects_rows_outside_range_and_empty_scopes(tmp_path: Path, monkeypatch, scope):
    client, engine, dataset = example(tmp_path, monkeypatch)
    endpoint = f"/api/datasets/{dataset['id']}/industrial/group-previews"
    samples = client.get(f"/api/datasets/{dataset['id']}/samples").json()["items"]
    payload = {"mode": "mapping", "scope": "selected", "sample_ids": [samples[0]["id"]], "mapping_text": json.dumps([
        {"relative_path": samples[0]["relative_path"], "capture_group_id": "part"},
        {"relative_path": samples[1]["relative_path"], "capture_group_id": "part"},
    ])}
    if scope == "batch":
        with Session(engine) as session:
            sample = session.get(Sample, samples[0]["id"])
            sample.capture_batch_id = "target-batch"
            session.add(sample)
            session.commit()
        payload.update(scope="batch", scope_capture_batch_id="target-batch")
        del payload["sample_ids"]
    response = client.post(endpoint, json=payload)
    assert response.status_code == 422
    assert "不在所选范围" in response.json()["detail"]
    assert samples[1]["relative_path"] in response.json()["detail"]
    for changes in (
        {"mode": "filename", "scope": "selected"},
        {"mode": "filename", "scope": "selected", "sample_ids": [999999]},
        {"mode": "filename", "scope": "batch"},
        {"mode": "filename", "scope": "batch", "scope_capture_batch_id": "unknown"},
        {"mode": "filename", "scope": "all", "sample_ids": [samples[0]["id"]]},
    ):
        assert client.post(endpoint, json=changes).status_code == 422
    assert client.get(f"/api/datasets/{dataset['id']}").json()["revision"] == dataset["revision"]


def test_group_all_and_legacy_unscoped_rules_still_check_full_dataset(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    endpoint = f"/api/datasets/{dataset['id']}/industrial/group-previews"
    for scope in ({}, {"scope": "all"}):
        response = client.post(endpoint, json={"mode": "filename", **scope})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == client.get(f"/api/datasets/{dataset['id']}/samples").json()["total"]
    with Session(engine) as session:
        sample = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"])).first()
        sample.relative_path = "unmatched.png"
        session.add(sample)
        session.commit()
    for scope in ({}, {"scope": "all"}):
        assert client.post(endpoint, json={"mode": "filename", **scope}).status_code == 422


@pytest.mark.parametrize("mode", ["selected", "filename", "directories", "csv-empty", "csv-omitted", "json"])
def test_group_preview_and_confirmation_keep_each_original_batch(tmp_path: Path, monkeypatch, mode):
    client, engine, dataset = example(tmp_path, monkeypatch)
    dataset_id = dataset["id"]
    endpoint = f"/api/datasets/{dataset_id}/industrial/group-previews"
    with Session(engine) as session:
        batch = DatasetBatch(dataset_id=dataset_id, name="正式批次", code="known-batch")
        session.add(batch)
        session.flush()
        samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)).all()
        if mode == "directories":
            for sample in samples:
                sample.relative_path = f"part/{sample.filename}"
        samples[0].batch_id = batch.id
        samples[0].capture_batch_id = batch.code
        # Historical records can have only one of the two fields populated.
        samples[1].capture_batch_id = "legacy-batch"
        samples[2].batch_id = batch.id
        samples[2].capture_batch_id = None
        samples[3].capture_batch_id = None
        expected = {sample.id: (sample.capture_batch_id, sample.batch_id) for sample in samples}
        selected = [sample.id for sample in samples[:4]]
        paths = [sample.relative_path for sample in samples[:4]]
        session.commit()
    if mode == "selected":
        payload = {"mode": mode, "sample_ids": selected, "capture_group_id": "part", "capture_batch_id": " "}
    elif mode in {"filename", "directories"}:
        payload = {"mode": mode}
    elif mode == "json":
        mapping = [{"relative_path": path, "capture_group_id": "part"} for path in paths]
        mapping[1]["capture_batch_id"] = None
        payload = {"mode": "mapping", "mapping_text": json.dumps(mapping)}
    else:
        columns = "relative_path,capture_group_id"
        lines = [f"{path},part" for path in paths]
        if mode == "csv-empty":
            columns += ",capture_batch_id"
            lines = [f"{line}, " for line in lines]
        payload = {"mode": "mapping", "mapping_text": "\n".join([columns, *lines])}
    response = client.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert {row["sample_id"] for row in plan["rows"]} == set(expected if mode in {"filename", "directories"} else selected)
    for row in plan["rows"]:
        assert row["batch_action"] == "keep"
        assert row["capture_batch_id"] == row["before_batch"] == expected[row["sample_id"]][0]
    response = client.post(f"{endpoint}/{plan['plan_id']}/confirm", json={
        "plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"]})
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        actual = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
        assert {sample.id: (sample.capture_batch_id, sample.batch_id) for sample in actual} == expected
        assert len(session.exec(select(DatasetBatch).where(DatasetBatch.dataset_id == dataset_id)).all()) == 1


def test_old_group_plan_cannot_clear_existing_batch(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    dataset_id = dataset["id"]
    endpoint = f"/api/datasets/{dataset_id}/industrial/group-previews"
    with Session(engine) as session:
        samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)).all()[:2]
        old_values = {sample.id: (sample.capture_group_id, sample.capture_batch_id) for sample in samples}
        rows = [
            dict(sample_id=sample.id, relative_path=sample.relative_path, file_hash=sample.file_hash,
                 capture_group_id="changed", capture_batch_id=batch)
            for sample, batch in zip(samples, ["a-new-batch", None], strict=True)
        ]
        plan = plans.freeze("groups", dataset_id, dataset["revision"], rows, {})
    response = client.post(f"{endpoint}/{plan['plan_id']}/confirm", json={
        "plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"]})
    assert response.status_code == 409
    assert "重新预览" in response.json()["detail"]
    with Session(engine) as session:
        for sample_id, previous in old_values.items():
            sample = session.get(Sample, sample_id)
            assert (sample.capture_group_id, sample.capture_batch_id) == previous
        assert not session.exec(select(DatasetBatch).where(DatasetBatch.dataset_id == dataset_id)).all()


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
