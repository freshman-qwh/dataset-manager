from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.models.sample import Sample
from test_capture_groups import example


@pytest.mark.parametrize("condition,content_count,record_count", [
    ("mixed", 8, 8), ("outdated", 8, 8), ("policy-outdated", 8, 8), ("unavailable", 8, 8),
    ("duplicate", 9, 10), ("missing-group", 10, 10),
])
def test_normal_candidate_filter_matches_whole_group_qualification(tmp_path, monkeypatch, condition, content_count, record_count):
    client, engine, dataset = example(tmp_path, monkeypatch)
    base = f"/api/datasets/{dataset['id']}"
    with Session(engine) as session:
        samples = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"]).order_by(Sample.filename)).all()
        first, second = samples[:2]
        if condition == "mixed":
            first.triage_status = "ng"
            first.ok_grade = None
        elif condition == "outdated":
            first.triaged_file_hash = "outdated"
        elif condition == "policy-outdated":
            first.triage_policy_version = 0
        elif condition == "unavailable":
            first.file_status = "missing"
        elif condition == "duplicate":
            second.file_hash = first.file_hash
            second.triaged_file_hash = first.file_hash
        else:
            first.capture_group_id = None
        session.add_all([first, second])
        session.commit()
        expected = {sample.id for sample in samples[:10]}
        if condition in {"mixed", "outdated", "policy-outdated", "unavailable"}:
            expected -= {first.id, second.id}
    ready = client.get(f"{base}/industrial/readiness").json()
    assert ready["normal_candidates"] == content_count
    response = client.get(f"{base}/samples", params={"normal_candidates_only": True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == ready["normal_candidate_records"] == record_count
    assert {sample["id"] for sample in result["items"]} == expected
    assert client.get(f"{base}/samples").json()["total"] == 16
    assert client.get(f"{base}/samples", params={"normal_candidates_only": False}).json()["total"] == 16
    filtered = client.get(f"{base}/samples", params={
        "normal_candidates_only": True, "capture_group_id": "part_01", "triage_status": "ok",
    }).json()
    expected_group = {second.id} if condition == "missing-group" else {first.id, second.id}
    assert {sample["id"] for sample in filtered["items"]} == expected.intersection(expected_group)


def test_candidate_filter_excludes_transitive_duplicate_connection_and_empty_scope(tmp_path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    base = f"/api/datasets/{dataset['id']}"
    with Session(engine) as session:
        samples = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"]).order_by(Sample.filename)).all()
        first, second = samples[:2]
        second.triage_status = "ng"
        second.ok_grade = None
        duplicate = samples[4]
        Path(duplicate.absolute_path).write_bytes(Path(first.absolute_path).read_bytes())
        duplicate.file_hash = duplicate.triaged_file_hash = first.file_hash
        session.add_all([second, duplicate])
        excluded_ids = {sample.id for sample in samples[:2] + samples[4:6]}
        session.commit()
    params = {"normal_candidates_only": True}
    ready = client.get(f"{base}/industrial/readiness").json()
    filtered = client.get(f"{base}/samples", params=params).json()
    assert ready["normal_candidate_records"] == filtered["total"] == 6
    assert {sample["id"] for sample in filtered["items"]}.isdisjoint(excluded_ids)
    with Session(engine) as session:
        for sample in session.exec(select(Sample).where(Sample.dataset_id == dataset["id"])).all():
            sample.triage_status = "pending"
            sample.ok_grade = None
            session.add(sample)
        session.commit()
    assert client.get(f"{base}/samples", params=params).json()["total"] == 0
    assert client.get(f"{base}/export-manifest", params=params).json()["exported_sample_count"] == 0


def test_candidate_scope_survives_paging_metadata_export_and_protocol_preview(tmp_path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    base = f"/api/datasets/{dataset['id']}"
    with Session(engine) as session:
        first = session.exec(select(Sample).where(Sample.dataset_id == dataset["id"]).order_by(Sample.filename)).first()
        first.triage_status = "ng"
        first.ok_grade = None
        session.add(first)
        session.commit()
    params = {"normal_candidates_only": True, "page_size": 3, "sort_by": "filename", "sort_order": "asc"}
    rows = []
    for page in range(1, 4):
        response = client.get(f"{base}/samples", params={**params, "page": page, "thumbnail_prefetch": 2})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == 8
        rows.extend(result["items"])
    ids = [sample["id"] for sample in rows]
    assert len(ids) == len(set(ids)) == 8
    assert [sample["filename"] for sample in rows] == sorted(sample["filename"] for sample in rows)
    manifest = client.get(f"{base}/export-manifest", params={"normal_candidates_only": True}).json()
    assert manifest["exported_sample_count"] == 8
    assert {sample["id"] for sample in manifest["samples"]} == set(ids)
    csv = client.get(f"{base}/export-template", params={
        "format": "csv", "scope": "filtered", "normal_candidates_only": True,
    }).json()
    assert csv["sample_count"] == 8
    query = {"normal_candidates_only": True}
    snapshot = client.post(f"{base}/snapshots", json={"sample_query": query}).json()
    assert snapshot["sample_count"] == 8
    plan = client.post(f"{base}/industrial/anomaly-previews", json={"sample_query": query}).json()
    assert plan["total"] == 8
    assert not any("范围外" in (row["exclusion_reason"] or "") for row in plan["rows"])
    saved = client.post(f"{base}/saved-views", json={"name": "纯正常候选", "sample_query": query})
    assert saved.status_code == 201, saved.text
    assert saved.json()["sample_query"]["normal_candidates_only"] is True


def test_next_step_and_filename_rule_survive_confirmation(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    base = f"/api/datasets/{dataset['id']}/industrial"
    ready = client.get(f"{base}/readiness").json()
    assert ready["next_step"] == "prepare"
    assert ready["normal_candidates"] == 10
    assert ready["normal_groups"] == 5
    assert client.get(f"{base}/group-rule").json() is None
    preview = client.post(f"{base}/group-previews", json={"mode": "filename", "capture_batch_id": "next-batch"}).json()
    assert preview["summary"]["group_count"] == 8
    assert preview["rows"][0]["capture_group_id"] == "part_01"
    assert client.get(f"{base}/group-rule").json() is None
    result = client.post(f"{base}/group-previews/{preview['plan_id']}/confirm", json={"plan_hash": preview["plan_hash"], "confirmation": preview["confirmation"]})
    assert result.status_code == 200, result.text
    assert client.get(f"{base}/group-rule").json()["keep_segments"] == 2
    with Session(engine) as session:
        sample = session.exec(select(Sample)).first()
        sample.triage_status = "untriaged"
        session.add(sample); session.commit()
    assert client.get(f"{base}/readiness").json()["next_step"] == "triage"


def test_filename_rule_rejects_ambiguous_and_preview_never_writes(tmp_path: Path, monkeypatch):
    client, engine, dataset = example(tmp_path, monkeypatch)
    base = f"/api/datasets/{dataset['id']}/industrial"
    response = client.post(f"{base}/group-previews", json={"mode": "filename", "filename_rule": {"delimiter": "-", "keep_segments": 1}})
    assert response.status_code == 422
    assert client.get(f"{base}/group-rule").json() is None
    with Session(engine) as session:
        sample = session.exec(select(Sample)).first()
        sample.triage_status = "pending"
        session.add(sample); session.commit()
    assert client.get(f"{base}/readiness").json()["next_step"] == "review"
