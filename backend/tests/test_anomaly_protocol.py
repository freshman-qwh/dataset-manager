from pathlib import Path

from sqlmodel import Session, select

from app.models.dataset import Dataset
from app.models.sample import Sample
from app.services.anomaly_protocol_service import _components
from app.services.dataset_revision_service import bump_dataset_revision
from test_capture_groups import example


def protocol(client, did, **kwargs):
    response = client.post(f"/api/datasets/{did}/industrial/anomaly-previews", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def test_protocol_group_isolation_pure_train_and_idempotent_writeback(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    did = dataset["id"]
    plan = protocol(client, did)
    assert not plan["summary"]["blocked"], plan
    splits = {}
    for r in plan["rows"]:
        assert r["split"] in {"train", "val", "test"}
        assert r["split"] != "train" or r["label_index"] == 0 and r["ok_grade"] == "clear"
        assert r["group_id"] not in splits or splits[r["group_id"]] == r["split"]
        splits[r["group_id"]] = r["split"]
    assert client.get(f"/api/datasets/{did}").json()["revision"] == dataset["revision"]
    assert all(s["split"] is None for s in client.get(f"/api/datasets/{did}/samples").json()["items"])
    body = {"plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"]}
    url = f"/api/datasets/{did}/industrial/anomaly-previews/{plan['plan_id']}/confirm-splits"
    result = client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert client.post(url, json=body).json() == result.json()
    fresh = client.get(f"/api/datasets/{did}/industrial/plans/{result.json()['plan_id']}")
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["dataset_revision"] == dataset["revision"] + 1
    assert client.get(f"/api/datasets/{did}/industrial/plans/{plan['plan_id']}").status_code == 409


def test_transitive_groups_duplicates_and_conflicting_labels(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    with Session(engine, expire_on_commit=False) as session:
        samples = list(session.exec(select(Sample).order_by(Sample.id)).all())
        # A--same part--B--same hash--C--same part--D is one component.
        samples[2].file_hash = samples[1].file_hash
        samples[2].triaged_file_hash = samples[1].file_hash
        Path(samples[2].absolute_path).write_bytes(Path(samples[1].absolute_path).read_bytes())
        for s in samples:
            session.add(s)
        session.commit()
        groups = _components(samples)
        assert any({s.id for s in samples[:4]}.issubset({s.id for s in members}) for members in groups.values())
    plan = protocol(client, dataset["id"])
    assert any(r["exclusion_reason"] == "精确重复，保留同组首张" for r in plan["rows"])
    with Session(engine, expire_on_commit=False) as session:
        sample = session.get(Sample, samples[2].id)
        sample.triage_status = "ng"
        sample.ok_grade = None
        session.add(sample)
        session.commit()
    conflict = protocol(client, dataset["id"])
    assert any("判定矛盾" in r for r in conflict["summary"]["blockers"])


def test_scope_outside_invalid_borderline_and_missing_identity(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    did = dataset["id"]
    with Session(engine, expire_on_commit=False) as session:
        samples = list(session.exec(select(Sample).order_by(Sample.id)).all())
        samples[0].triage_status = "pending"
        samples[2].ok_grade = "borderline"
        samples[4].ok_grade = None
        samples[6].triaged_file_hash = "old"
        samples[8].capture_group_id = None
        for s in samples: session.add(s)
        session.commit()
    plan = protocol(client, did)
    assert plan["summary"]["blocked"]
    assert not any(r["split"] == "train" for r in plan["rows"] if r["sample_id"] in {s.id for s in samples[:8]})
    allowed = protocol(client, did, include_borderline_evaluation=True, independent_capture_declared=True)
    assert all(r["split"] != "train" for r in allowed["rows"] if r["sample_id"] in {samples[2].id, samples[3].id})
    restricted = protocol(client, did, sample_query={"sample_ids": [samples[10].id]})
    assert restricted["rows"][0]["split"] is None
    assert "范围外" in restricted["rows"][0]["exclusion_reason"]


def test_mixed_groups_never_train_and_small_protocol_is_blocked(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    did = dataset["id"]
    with Session(engine, expire_on_commit=False) as session:
        samples = list(session.exec(select(Sample).order_by(Sample.id)).all())
        samples[0].triage_status = "ng"
        samples[0].ok_grade = None
        session.add(samples[0]); session.commit()
    plan = protocol(client, did)
    assert not plan["summary"]["blocked"]
    assert all(r["split"] in {"val", "test"} for r in plan["rows"] if r["sample_id"] in {samples[0].id, samples[1].id})
    forbidden = protocol(client, did, overrides={f"group-{samples[0].id}": "train"})
    assert forbidden["summary"]["blocked"]
    small = protocol(client, did, sample_query={"sample_ids": [s.id for s in samples[:2]]})
    assert small["summary"]["blocked"]
    bad = client.post(f"/api/datasets/{did}/industrial/anomaly-previews/{small['plan_id']}/confirm-splits",
                      json={"plan_hash": small["plan_hash"], "confirmation": small["confirmation"]})
    assert bad.status_code == 409


def test_source_change_rejects_entire_writeback(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    did = dataset["id"]
    plan = protocol(client, did)
    with Session(engine, expire_on_commit=False) as session:
        sample = session.get(Sample, plan["rows"][-1]["sample_id"])
        Path(sample.absolute_path).write_bytes(b"changed")
    bad = client.post(f"/api/datasets/{did}/industrial/anomaly-previews/{plan['plan_id']}/confirm-splits",
                      json={"plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"]})
    assert bad.status_code == 409
    assert all(s["split"] is None for s in client.get(f"/api/datasets/{did}/samples").json()["items"])
    assert client.get(f"/api/datasets/{did}").json()["revision"] == dataset["revision"]


def test_preserve_existing_checks_deduplicated_group_members(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    with Session(engine, expire_on_commit=False) as session:
        samples = list(session.exec(select(Sample).order_by(Sample.id)).all())
        samples[1].file_hash = samples[0].file_hash
        samples[1].triaged_file_hash = samples[0].file_hash
        Path(samples[1].absolute_path).write_bytes(Path(samples[0].absolute_path).read_bytes())
        samples[0].split, samples[1].split = "train", "val"
        session.add_all(samples[:2]); session.commit()
    plan = protocol(client, dataset["id"], preserve_existing=True)
    assert plan["summary"]["blocked"]
    assert any("已有划分跨集合" in reason for reason in plan["summary"]["blockers"])
