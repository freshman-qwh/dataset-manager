"""Explicit human review candidates, separate from frozen prediction truth."""
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.sample import Sample
from app.models.validation import ValidationDecision, ValidationReview
from app.services import validation_run_service as runs


def add_candidates(session: Session, run_id: str, sample_ids: list[int]) -> dict:
    run, contract, _ = runs.load_result(session, run_id)
    allowed = {r["sample_id"]: r for r in contract["rows"] if r["split"] and
               (r["split"] != "test" or session.get(ValidationDecision, run_id))}
    checked = []
    for sid in set(sample_ids):
        row, sample = allowed.get(sid), session.get(Sample, sid)
        if not row or not sample or sample.dataset_id != run.dataset_id or sample.file_hash != row["sha256"]:
            raise HTTPException(409, "图片不在已开启的结果中，或当前文件已变化；本次未添加候选。")
        checked.append((sid, row))
    for sid, row in checked:
        item = session.get(ValidationReview, (run_id, sid))
        if item is None:
            session.add(ValidationReview(run_id=run_id, sample_id=sid, sha256=row["sha256"]))
        elif item.state != "pending":
            item.state = "pending"; item.updated_at = utc_now(); session.add(item)
    session.commit()
    return summary(session, run_id)


def summary(session: Session, run_id: str) -> dict:
    run = runs.get_run(session, run_id)
    items = session.exec(select(ValidationReview).where(ValidationReview.run_id == run_id)).all()
    return dict(dataset_id=run.dataset_id, pending=sum(r.state == "pending" for r in items),
        reviewed=sum(r.state == "reviewed" for r in items), ignored=sum(r.state == "ignored" for r in items))


def pending_ids(session: Session, dataset_id: int, run_id: str) -> list[int]:
    run = runs.get_run(session, run_id)
    if run.dataset_id != dataset_id:
        raise HTTPException(422, "复查队列与当前项目不一致。")
    return list(session.exec(select(ValidationReview.sample_id).join(Sample, Sample.id == ValidationReview.sample_id).where(
        ValidationReview.run_id == run_id, ValidationReview.state == "pending",
        Sample.dataset_id == dataset_id, Sample.file_hash == ValidationReview.sha256)).all())


def update(session: Session, run_id: str, sid: int, payload) -> dict:
    runs.get_run(session, run_id)
    item = session.get(ValidationReview, (run_id, sid))
    sample = session.get(Sample, sid)
    if not item or not sample or item.sha256 != sample.file_hash:
        raise HTTPException(409, "复查候选已不存在或图片内容已变化。")
    if payload.state == "reviewed":
        dataset = runs.get_dataset_or_404(session, sample.dataset_id)
        if (payload.expected_version != sample.triage_version or payload.expected_file_hash != sample.file_hash or
            sample.triage_status not in {"ok", "ng"} or sample.triaged_file_hash != sample.file_hash or
            sample.triage_policy_version != dataset.triage_policy_version):
            raise HTTPException(409, "先保存有效人工判定，再标记已复核；当前图片或版本已变化。")
    item.state = payload.state; item.updated_at = utc_now(); session.add(item); session.commit()
    return summary(session, run_id)
