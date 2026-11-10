import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.delivery_checklist import router
from app.core.database import get_session
from app.models.dataset import Dataset
from app.models.defect_type import DefectType, SampleDefectLink
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.schemas.industrial import AnomalyPreviewRequest
from app.schemas.validation import ValidationPreviewRequest
from app.services import anomaly_protocol_service as protocol, delivery_checklist, validation_plan_service
from test_capture_groups import example


@pytest.fixture
def checklist_workspace(tmp_path, monkeypatch):
    _, engine, dataset = example(tmp_path, monkeypatch)
    api = FastAPI()
    api.include_router(router)

    def override():
        with Session(engine) as session:
            yield session

    api.dependency_overrides[get_session] = override
    with TestClient(api) as client:
        yield client, engine, dataset


def inspect(client, dataset_id, **payload):
    response = client.post(f"/api/datasets/{dataset_id}/delivery-checklist", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def samples(engine, dataset_id):
    with Session(engine, expire_on_commit=False) as session:
        return list(session.exec(select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)).all())


@pytest.mark.parametrize("target", ["training_package", "evaluation", "exploration"])
def test_checklist_reuses_exact_real_plan_and_returns_usable_confirmation(checklist_workspace, monkeypatch, target):
    client, engine, dataset = checklist_workspace
    did = dataset["id"]
    with Session(engine) as session:
        if target == "training_package":
            reference = protocol.preview(session, did, AnomalyPreviewRequest())
        else:
            reference = validation_plan_service.preview(session, did, ValidationPreviewRequest(mode=target))
    calls = []
    owner = protocol if target == "training_package" else validation_plan_service
    real_preview = owner.preview

    def tracked(*args, **kwargs):
        calls.append(args)
        return real_preview(*args, **kwargs)

    monkeypatch.setattr(owner, "preview", tracked)
    report = inspect(client, did, target=target)
    assert len(calls) == 1
    assert report["ready"] is (not reference["summary"]["blocked"])
    assert report["plan"]["summary"] == reference["summary"]
    assert report["plan"]["rows"] == reference["rows"]
    assert [issue["title"] for issue in report["issues"] if issue["severity"] == "blocker"] == reference["summary"]["blockers"]
    with Session(engine) as session:
        plan = report["plan"]
        if target == "training_package":
            assert protocol.validate_plan(session, did, plan["plan_id"], plan["plan_hash"])["kind"] == "anomaly"
        else:
            assert validation_plan_service.validate(session, did, plan["plan_id"], plan["plan_hash"])["kind"] == "validation"
    if target == "exploration":
        assert any("没有异常检出率" in note for note in report["notes"])


def test_exclusions_cover_complete_plan_after_first_page_and_no_metadata_writes(checklist_workspace):
    client, engine, dataset = checklist_workspace
    did = dataset["id"]
    with Session(engine) as session:
        session.add_all([Sample(dataset_id=did, filename=f"pending-{i:02}.png", relative_path=f"pending-{i:02}.png",
            absolute_path=f"C:/unread-pending/{i}.png", extension=".png", file_type="image", file_hash=f"pending-{i}",
            triage_status="pending", capture_group_id=f"pending-{i}") for i in range(60)])
        session.commit()
        before = {sample.id: sample.model_dump() for sample in session.exec(select(Sample)).all()}
        dataset_before = session.get(Dataset, did).model_dump()
    originals = {sample.absolute_path: hashlib.sha256(Path(sample.absolute_path).read_bytes()).hexdigest()
                 for sample in samples(engine, did) if Path(sample.absolute_path).is_file()}
    report = inspect(client, did)
    assert report["plan"]["total"] > 50 and len(report["plan"]["rows"]) == 50
    excluded = [issue for issue in report["issues"] if issue["severity"] == "excluded"]
    assert sum(issue["count"] for issue in excluded) == 60
    assert sum(len(issue["sample_ids"]) for issue in excluded) == 60
    assert all(len(issue["samples"]) <= 6 for issue in excluded)
    assert sum(row["pending"] for row in report["coverage"]["categories"]) == 60
    with Session(engine) as session:
        assert {sample.id: sample.model_dump() for sample in session.exec(select(Sample)).all()} == before
        assert session.get(Dataset, did).model_dump() == dataset_before
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in originals.items())


def test_scope_does_not_expand_but_review_includes_outside_group_member(checklist_workspace):
    client, engine, dataset = checklist_workspace
    current = samples(engine, dataset["id"])
    report = inspect(client, dataset["id"], protocol={"sample_query": {"sample_ids": [current[0].id]}})
    assert report["plan"]["total"] == 1
    assert report["plan"]["rows"][0]["sample_id"] == current[0].id
    outside = next(issue for issue in report["issues"] if "范围外" in issue["title"])
    assert outside["count"] == 1 and outside["action"] == "scope"
    assert set(outside["sample_ids"]) == {current[0].id, current[1].id}
    assert sum(row["total"] for row in report["coverage"]["categories"]) == 1
    assert sum(row["normal_groups"] for row in report["coverage"]["categories"]) == 0


def test_conflicting_labels_and_missing_groups_have_actionable_blockers(checklist_workspace):
    client, engine, dataset = checklist_workspace
    current = samples(engine, dataset["id"])
    with Session(engine) as session:
        first, second = session.get(Sample, current[0].id), session.get(Sample, current[1].id)
        Path(second.absolute_path).write_bytes(Path(first.absolute_path).read_bytes())
        second.file_hash = second.triaged_file_hash = first.file_hash
        second.triage_status = "ng"
        second.ok_grade = None
        loose = session.get(Sample, current[2].id)
        loose.capture_group_id = None
        session.add_all([second, loose])
        session.commit()
    report = inspect(client, dataset["id"])
    blockers = [issue for issue in report["issues"] if issue["severity"] == "blocker"]
    conflict = next(issue for issue in blockers if "判定矛盾" in issue["title"])
    assert conflict["action"] == "triage"
    assert set(conflict["sample_ids"]) == {current[0].id, current[1].id}
    missing = next(issue for issue in blockers if "缺少采集分组" in issue["title"])
    assert missing["action"] == "groups" and current[2].id in missing["sample_ids"]
    assert report["ready"] is False


def test_coverage_respects_current_human_truth_scope_and_defect_group_count(checklist_workspace):
    client, engine, dataset = checklist_workspace
    did = dataset["id"]
    current = samples(engine, did)
    with Session(engine) as session:
        category = DatasetCategory(dataset_id=did, name="探针")
        batch = DatasetBatch(dataset_id=did, name="首批")
        defect = DefectType(dataset_id=did, name="划伤", code="scratch")
        session.add_all([category, batch, defect])
        session.flush()
        for index, row in enumerate(current):
            sample = session.get(Sample, row.id)
            sample.category_id, sample.batch_id = category.id, batch.id
            if index == 0:
                sample.triage_status = "pending"
            elif index == 2:
                sample.triaged_file_hash = "old"
            elif index == 4:
                sample.file_status = "missing"
            session.add(sample)
        ng = [sample for sample in current if sample.triage_status == "ng"][:2]
        session.add_all([SampleDefectLink(sample_id=sample.id, defect_type_id=defect.id) for sample in ng])
        session.commit()
        category_id, batch_id = category.id, batch.id
    report = inspect(client, did)
    category = report["coverage"]["categories"][0]
    assert category["id"] == category_id and category["name"] == "探针"
    assert category["pending"] == 3
    assert category["total"] == len(current)
    assert report["coverage"]["batches"][0]["id"] == batch_id
    assert report["coverage"]["defects"][0]["total"] == 2
    assert report["coverage"]["defects"][0]["groups"] == 1
    notice = next(issue for issue in report["issues"] if issue["key"].startswith("defect-coverage"))
    assert notice["severity"] == "notice" and notice["action"] == "collect"
    assert all("mask" not in row for row in report["plan"]["rows"])


def test_validation_target_preserves_official_test_category_and_roi_guards(checklist_workspace):
    client, engine, dataset = checklist_workspace
    did = dataset["id"]
    current = samples(engine, did)
    with Session(engine) as session:
        categories = [DatasetCategory(dataset_id=did, name=name) for name in ("A", "B")]
        session.add_all(categories)
        session.flush()
        for index, row in enumerate(current):
            sample = session.get(Sample, row.id)
            sample.category_id = categories[index // 2 % 2].id
            if sample.triage_status == "ok":
                sample.official_split = "test"
            session.add(sample)
        session.commit()
    report = inspect(client, did, target="evaluation", roi={"x": 0, "y": 0, "width": .001, "height": .5})
    blockers = [issue["title"] for issue in report["issues"] if issue["severity"] == "blocker"]
    assert any("官方测试" in title for title in blockers)
    assert any("单一对象类别" in title for title in blockers)
    assert any("区域检查失败" in title for title in blockers)
    assert report["ready"] is False


def test_empty_foreign_ids_stale_revision_and_invalid_goal_are_rejected(checklist_workspace):
    client, engine, dataset = checklist_workspace
    did = dataset["id"]
    endpoint = f"/api/datasets/{did}/delivery-checklist"
    for target in ("training_package", "evaluation", "exploration"):
        assert client.post(endpoint, json={"target": target, "protocol": {"sample_query": {"search": "no-match"}}}).status_code == 422
        assert client.post(endpoint, json={"target": target, "protocol": {"sample_query": {"sample_ids": [999999]}}}).status_code == 422
    assert client.post(endpoint, json={"protocol": {"sample_query": {"expected_dataset_revision": 999999}}}).status_code == 409
    assert client.post(endpoint, json={"target": "production"}).status_code == 422
    assert client.post(endpoint, json={"image_size": 999}).status_code == 422


def test_cpu_limits_are_the_original_validation_planners_decision(checklist_workspace, tmp_path):
    client, engine, dataset = checklist_workspace
    did = dataset["id"]
    template = next(sample for sample in samples(engine, did) if sample.triage_status == "ok")
    original = Path(template.absolute_path).read_bytes()
    with Session(engine) as session:
        for index in range(400):
            path = tmp_path / f"cpu-normal-{index}.png"
            content = original + f"cpu-normal-{index}".encode()
            path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            session.add(Sample(dataset_id=did, filename=path.name, relative_path=path.name,
                absolute_path=str(path), extension=".png", file_type="image", file_hash=digest,
                capture_group_id=f"cpu-{index}", triage_status="ok", ok_grade="clear",
                triaged_file_hash=digest, triage_policy_version=template.triage_policy_version))
        session.commit()
    report = inspect(client, did, target="evaluation")
    assert report["ready"] is False
    cpu = next(issue for issue in report["issues"] if "CPU 快速验证" in issue["title"])
    assert cpu["severity"] == "blocker" and cpu["action"] == "scope"
    assert report["plan"]["summary"]["counts"]["train"]["normal"] > 256
