import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.batch_reception import router
from app.core.config import get_settings
from app.core.database import get_session
from app.models.dataset import Dataset
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.services import batch_reception, industrial_plan_service as plans


@pytest.fixture
def reception_client(tmp_path: Path, monkeypatch):
    settings = get_settings().model_copy(update={"storage_root": tmp_path / "storage"})
    monkeypatch.setattr(plans, "get_settings", lambda: settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Reception", workflow_profile="industrial_anomaly", revision=5,
            industrial_settings_json=json.dumps({"untouched": {"key": "value"},
                "validation_roi": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8}}))
        foreign = Dataset(name="Foreign", workflow_profile="industrial_anomaly")
        session.add_all([dataset, foreign])
        session.flush()
        categories = [DatasetCategory(dataset_id=dataset.id, name="A"),
            DatasetCategory(dataset_id=dataset.id, name="B"),
            DatasetCategory(dataset_id=foreign.id, name="Other")]
        batches = [DatasetBatch(dataset_id=dataset.id, name="First", code="first"),
            DatasetBatch(dataset_id=dataset.id, name="Second", code="second"),
            DatasetBatch(dataset_id=foreign.id, name="Foreign", code="foreign")]
        session.add_all(categories + batches)
        session.flush()
        rows = []
        for index, path in enumerate(["folder/part_001_camA.png", "folder/deep/part_002_camB.png", "odd.png", "folder/part_003_camA.png"]):
            source = tmp_path / "images" / path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(f"original-{index}".encode())
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            sample = Sample(dataset_id=dataset.id, filename=source.name, relative_path=path,
                absolute_path=str(source), extension=".png", file_type="image", file_hash=digest,
                batch_id=batches[0 if index < 3 else 1].id, capture_batch_id="first" if index < 3 else "second",
                triage_status="ok" if index == 0 else "ng" if index == 1 else "untriaged",
                ok_grade="clear" if index == 0 else None, triage_note="original note" if index < 2 else None,
                triage_version=3 if index < 2 else 0, triage_policy_version=1 if index < 2 else None,
                triaged_file_hash=digest if index < 2 else None, split="train" if index == 0 else "test" if index == 1 else None)
            session.add(sample)
            session.flush()
            rows.append(sample.id)
        session.commit()
        ids = {"dataset": dataset.id, "foreign": foreign.id, "a": categories[0].id, "b": categories[1].id,
            "foreign_category": categories[2].id, "batch": batches[0].id, "second": batches[1].id,
            "foreign_batch": batches[2].id, "samples": rows}
    api = FastAPI()
    api.include_router(router)

    def override_session():
        with Session(engine) as session:
            yield session

    api.dependency_overrides[get_session] = override_session
    with TestClient(api) as client:
        yield client, engine, ids
    engine.dispose()


def base(ids):
    return f"/api/datasets/{ids['dataset']}/batch-reception"


def save_recipe(client, ids, **overrides):
    profile = {"name": "Repeatable intake", "import_format": "folder",
        "filename_rule": {"delimiter": "_", "keep_segments": 2, "include_parent": False},
        "category_rules": [{"directory": ".", "category_id": ids["a"]},
            {"directory": "folder/deep", "category_id": ids["b"]}]}
    profile.update(overrides)
    old = client.get(base(ids) + "/profile").json()
    response = client.put(base(ids) + "/profile", json={"expected_revision": old["dataset_revision"], "profile": profile})
    assert response.status_code == 200, response.text
    return response.json()


def preview(client, ids):
    current = client.get(base(ids) + "/profile").json()
    response = client.post(base(ids) + "/previews", json={"batch_id": ids["batch"], "expected_revision": current["dataset_revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, ids, plan, **overrides):
    payload = {"plan_hash": plan["plan_hash"], "confirmation": plan["confirmation"]}
    payload.update(overrides)
    return client.post(base(ids) + f"/previews/{plan['plan_id']}/confirm", json=payload)


def test_profile_persists_optimistically_and_preserves_existing_settings(reception_client):
    client, engine, ids = reception_client
    before = client.get(base(ids) + "/profile").json()
    assert before["dataset_revision"] == 5
    assert before["saved"] is False
    assert before["context"]["roi"]["width"] == 0.8
    saved = save_recipe(client, ids)
    assert saved["dataset_revision"] == 6
    assert saved["saved"] is True
    assert client.get(base(ids) + "/profile").json() == saved
    assert client.put(base(ids) + "/profile", json={"expected_revision": 5, "profile": saved["profile"]}).status_code == 409
    with Session(engine) as session:
        settings = json.loads(session.get(Dataset, ids["dataset"]).industrial_settings_json)
        assert settings["untouched"] == {"key": "value"}
        assert settings["validation_roi"] == before["context"]["roi"]
    unchanged = client.put(base(ids) + "/profile", json={"expected_revision": 6, "profile": saved["profile"]})
    assert unchanged.json()["dataset_revision"] == 6


def test_preview_requires_an_explicitly_saved_profile(reception_client):
    client, _, ids = reception_client
    response = client.post(base(ids) + "/previews", json={"batch_id": ids["batch"], "expected_revision": 5})
    assert response.status_code == 409
    assert "先保存" in response.json()["detail"]


@pytest.mark.parametrize("directory", ["../outside", "/absolute", "C:/absolute", "a/../b", "a/./b", "\\\\server\\share", "\0x"])
def test_profile_rejects_unsafe_directory_rules(reception_client, directory):
    client, _, ids = reception_client
    response = client.put(base(ids) + "/profile", json={"expected_revision": 5,
        "profile": {"category_rules": [{"directory": directory, "category_id": ids["a"]}]}})
    assert response.status_code == 422


def test_profile_rejects_duplicate_normalized_rules_and_foreign_categories(reception_client):
    client, _, ids = reception_client
    for rules in ([{"directory": "folder\\deep/", "category_id": ids["a"]},
                    {"directory": "folder/deep", "category_id": ids["b"]}],
                  [{"directory": ".", "category_id": ids["foreign_category"]}]):
        response = client.put(base(ids) + "/profile", json={"expected_revision": 5, "profile": {"category_rules": rules}})
        assert response.status_code == 422
    assert client.get(base(ids) + "/profile").json()["dataset_revision"] == 5


def test_batch_preview_longest_mapping_and_confirmation_preserve_truth_and_sources(reception_client):
    client, engine, ids = reception_client
    save_recipe(client, ids)
    with Session(engine) as session:
        before = {sample.id: sample.model_dump() for sample in session.exec(select(Sample)).all()}
    source_before = {row["absolute_path"]: Path(row["absolute_path"]).read_bytes() for row in before.values()}
    plan = preview(client, ids)
    assert plan["kind"] == "batch_reception" and plan["total"] == 3
    assert plan["confirmation"] == "确认接收批次元数据 3 张图片"
    assert plan["summary"]["image_count"] == 3
    assert plan["summary"]["untriaged_count"] == 1
    assert plan["summary"]["unmatched_count"] == 1
    assert plan["summary"]["blocked"] is False
    by_id = {row["sample_id"]: row for row in plan["rows"]}
    assert by_id[ids["samples"][0]]["category_id"] == ids["a"]
    assert by_id[ids["samples"][1]]["category_id"] == ids["b"]
    assert by_id[ids["samples"][0]]["capture_group_id"] == "part_001"
    assert by_id[ids["samples"][2]]["capture_group_id"] is None
    assert confirm(client, ids, plan, confirmation="wrong").status_code == 409
    applied = confirm(client, ids, plan)
    assert applied.status_code == 200, applied.text
    assert applied.json() == {"dataset_revision": 7, "updated_count": 3, "plan_id": None, "plan_hash": None}
    assert confirm(client, ids, plan).json() == applied.json()
    assert confirm(client, ids, plan, confirmation="wrong").status_code == 409
    with Session(engine) as session:
        after = {sample.id: sample.model_dump() for sample in session.exec(select(Sample)).all()}
    for identity, row in before.items():
        expected = dict(row)
        if identity in by_id:
            expected.update(category_id=by_id[identity]["category_id"], capture_group_id=by_id[identity]["capture_group_id"])
        assert after[identity] == expected
    assert {path: Path(path).read_bytes() for path in source_before} == source_before


def test_existing_metadata_conflicts_block_whole_batch(reception_client):
    client, engine, ids = reception_client
    save_recipe(client, ids)
    with Session(engine) as session:
        sample = session.get(Sample, ids["samples"][0])
        sample.category_id = ids["b"]
        sample.capture_group_id = "manually-established"
        session.add(sample)
        session.commit()
    plan = preview(client, ids)
    assert plan["summary"]["blocked"] is True
    assert plan["summary"]["conflict_count"] == 1
    assert confirm(client, ids, plan).status_code == 409
    with Session(engine) as session:
        assert session.get(Sample, ids["samples"][1]).category_id is None
        assert session.get(Sample, ids["samples"][0]).capture_group_id == "manually-established"


def test_single_letter_directory_overrides_root_fallback(reception_client):
    client, engine, ids = reception_client
    save_recipe(client, ids, category_rules=[{"directory": ".", "category_id": ids["a"]},
        {"directory": "x", "category_id": ids["b"]}])
    with Session(engine) as session:
        sample = session.get(Sample, ids["samples"][1])
        sample.relative_path = "x/part_002_camB.png"
        session.add(sample)
        session.commit()
    plan = preview(client, ids)
    assert next(row for row in plan["rows"] if row["sample_id"] == ids["samples"][1])["category_id"] == ids["b"]


def test_confirmation_hashes_before_write_lock_and_rejects_later_source_changes(reception_client, monkeypatch):
    client, engine, ids = reception_client
    save_recipe(client, ids)
    plan = preview(client, ids)
    original_fingerprint = batch_reception._source_fingerprint
    write_lock = False
    checked = 0

    def fingerprint(path, digest):
        nonlocal checked
        assert not write_lock, "Read source bytes before taking SQLite's write lock"
        checked += 1
        return original_fingerprint(path, digest)

    def mutate_after_precheck(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal write_lock
        if statement.lstrip().upper() == "BEGIN IMMEDIATE":
            write_lock = True
            Path(plan["rows"][1]["source_absolute_path"]).write_bytes(b"changed between hash and transaction")

    monkeypatch.setattr(batch_reception, "_source_fingerprint", fingerprint)
    event.listen(engine, "before_cursor_execute", mutate_after_precheck)
    try:
        response = confirm(client, ids, plan)
    finally:
        event.remove(engine, "before_cursor_execute", mutate_after_precheck)
    assert checked == 3
    assert response.status_code == 409
    with Session(engine) as session:
        assert session.get(Sample, ids["samples"][0]).category_id is None


@pytest.mark.parametrize("mutation", ["source", "revision", "profile", "row"])
def test_stale_reception_plans_reject_changes_and_roll_back(reception_client, mutation):
    client, engine, ids = reception_client
    saved = save_recipe(client, ids)
    plan = preview(client, ids)
    if mutation == "source":
        with Session(engine) as session:
            path = session.get(Sample, ids["samples"][1]).absolute_path
        Path(path).write_bytes(b"changed after preview")
    elif mutation == "profile":
        changed = client.put(base(ids) + "/profile", json={"expected_revision": saved["dataset_revision"],
            "profile": {**saved["profile"], "name": "Changed recipe"}})
        assert changed.status_code == 200
    else:
        with Session(engine) as session:
            if mutation == "revision":
                dataset = session.get(Dataset, ids["dataset"])
                dataset.revision += 1
                session.add(dataset)
            else:
                sample = session.get(Sample, ids["samples"][1])
                sample.capture_group_id = "external-without-revision"
                session.add(sample)
            session.commit()
    assert confirm(client, ids, plan).status_code == 409
    with Session(engine) as session:
        assert session.get(Sample, ids["samples"][0]).category_id is None


def test_unmatched_rules_are_visible_and_duplicates_do_not_merge_groups(reception_client):
    client, engine, ids = reception_client
    save_recipe(client, ids, category_rules=[{"directory": "unmatched", "category_id": ids["a"]}])
    with Session(engine) as session:
        first = session.get(Sample, ids["samples"][0])
        second = session.get(Sample, ids["samples"][3])
        Path(second.absolute_path).write_bytes(Path(first.absolute_path).read_bytes())
        second.file_hash = first.file_hash
        session.add(second)
        session.commit()
    plan = preview(client, ids)
    assert plan["summary"]["unmatched_count"] == 3
    assert plan["summary"]["duplicate_count"] == 1
    assert plan["summary"]["blocked"] is False
    assert confirm(client, ids, plan).status_code == 200
    with Session(engine) as session:
        assert session.get(Sample, ids["samples"][0]).capture_group_id == "part_001"
        assert session.get(Sample, ids["samples"][3]).capture_group_id is None


def test_batch_scope_empty_foreign_unavailable_and_capacity(reception_client, monkeypatch):
    client, engine, ids = reception_client
    save_recipe(client, ids)
    revision = client.get(base(ids) + "/profile").json()["dataset_revision"]
    assert client.post(base(ids) + "/previews", json={"batch_id": ids["foreign_batch"], "expected_revision": revision}).status_code == 422
    assert client.post(base(ids) + "/previews", json={"batch_id": ids["batch"], "expected_revision": 1}).status_code == 409
    with Session(engine) as session:
        empty = DatasetBatch(dataset_id=ids["dataset"], name="Empty", code="empty")
        session.add(empty)
        session.commit()
        empty_id = empty.id
        sample = session.get(Sample, ids["samples"][0])
        sample.file_status = "missing"
        session.add(sample)
        session.commit()
    assert client.post(base(ids) + "/previews", json={"batch_id": empty_id, "expected_revision": revision}).status_code == 422
    plan = preview(client, ids)
    assert plan["summary"]["source_error_count"] == 1
    assert confirm(client, ids, plan).status_code == 409
    monkeypatch.setattr(batch_reception, "MAX_SAMPLES", 1)
    assert client.post(base(ids) + "/previews", json={"batch_id": ids["batch"], "expected_revision": revision}).status_code == 422
