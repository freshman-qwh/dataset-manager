from pathlib import Path

from sqlmodel import Session, select

from app.models.sample import Sample
from test_capture_groups import example


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
