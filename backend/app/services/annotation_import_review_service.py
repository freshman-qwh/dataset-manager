"""Review a committed import using the existing annotation workspace.

The receipt lives beside the rollback journal, outside the bounded job JSON.
It records committed targets only and never writes into a raw dataset folder.
"""
import json
import os
from hashlib import sha256
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.job import Job
from app.models.sample import Sample
from app.schemas.annotation import AnnotationRead
from app.schemas.annotation_import import AnnotationImportConfirmRequest, AnnotationImportReview
from app.services import annotation_service, dataset_service
from app.services.dataset_revision_service import bump_dataset_revision


class ReviewEntry(BaseModel):
    sample_id: int
    fingerprint: str
    eligible: bool


def _receipt_path(job_id: int) -> Path:
    from app.services.annotation_import_job_service import _journal_path
    return _journal_path(job_id).with_name("annotation-import-review.json")


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _sample_state(sample: Sample, annotations: list[AnnotationRead]) -> dict[str, object]:
    try:
        stat = Path(sample.absolute_path).stat()
        file_state = [stat.st_size, stat.st_mtime_ns]
    except OSError:
        file_state = None
    return {"sample_id": sample.id, "updated_at": sample.updated_at.replace(tzinfo=None).isoformat(),
            "progress": sample.annotation_progress, "review_status": sample.review_status,
            "file_status": sample.file_status, "file_state": file_state,
            "annotations": [item.model_dump(mode="json", exclude={"created_at", "updated_at"}) for item in annotations]}


def capture_entries(session: Session, sample_ids: list[int], ineligible: frozenset[int]) -> list[dict]:
    annotations = annotation_service.annotations_by_sample(session, sample_ids)
    return [ReviewEntry(sample_id=sample.id, fingerprint=_digest(_sample_state(sample, annotations.get(sample.id, []))),
                       eligible=sample.id not in ineligible).model_dump()
            for sample in session.exec(select(Sample).where(Sample.id.in_(sample_ids))).all()]


def persist_receipt(job_id: int, entries: list[dict]) -> None:
    path = _receipt_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _entries(session: Session, dataset_id: int, job_id: int) -> list[ReviewEntry]:
    if "jobs" not in inspect(session.get_bind()).get_table_names():
        raise HTTPException(404, "本次导入的复查记录不可用。")
    job = session.get(Job, job_id)
    if not job or job.dataset_id != dataset_id or job.job_type not in {"annotation.import", "annotation.import.labelme"}:
        raise HTTPException(404, "找不到本数据集的导入任务。")
    result = json.loads(job.result_json or "{}")
    if job.status != "succeeded" or not result.get("review_available"):
        raise HTTPException(409, "导入尚未完成，或此历史任务没有复查记录。")
    journal_id = result.get("source_job_id", job.id)
    rollbacks = session.exec(select(Job).where(Job.dataset_id == dataset_id,
        Job.job_type.in_(["annotation.import.rollback", "annotation.import.labelme.rollback"]))).all()
    if any(json.loads(item.parameters_json).get("journal_job_id") == journal_id
           and (item.status in {"queued", "running", "succeeded"} or item.progress_current > 0) for item in rollbacks):
        raise HTTPException(409, "本次导入已回滚或正在回滚，请返回数据集查看当前结果。")
    try:
        return [ReviewEntry.model_validate(item) for item in json.loads(_receipt_path(job_id).read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(409, "本次导入的复查记录不可用。") from exc


def review_sample_ids(session: Session, dataset_id: int, job_id: int) -> list[int]:
    return [item.sample_id for item in _entries(session, dataset_id, job_id)]


def _review(session: Session, dataset_id: int, job_id: int) -> tuple[AnnotationImportReview, list[tuple[Sample, bool]]]:
    entries = _entries(session, dataset_id, job_id)
    ids = [item.sample_id for item in entries]
    samples = {sample.id: sample for sample in session.exec(
        select(Sample).where(Sample.dataset_id == dataset_id, Sample.id.in_(ids))).all()}
    annotations = annotation_service.annotations_by_sample(session, ids)
    states = []
    pending: list[tuple[Sample, bool]] = []
    completed = 0
    for entry in entries:
        sample = samples.get(entry.sample_id)
        if sample is None:
            states.append({"sample_id": entry.sample_id, "missing": True})
            continue
        state = _sample_state(sample, annotations.get(sample.id, []))
        states.append(state)
        if sample.annotation_progress in {"completed_empty", "completed_with_objects"}:
            completed += 1
        else:
            safe = entry.eligible and sample.file_status == "normal" and state["file_state"] is not None and _digest(state) == entry.fingerprint
            pending.append((sample, safe))
    confirmable = sum(safe for _, safe in pending)
    return AnnotationImportReview(job_id=job_id, total=len(entries), completed=completed, confirmable=confirmable,
        needs_individual_review=len(entries) - completed - confirmable,
        first_sample_id=next(iter(samples), None), fingerprint=_digest(states)), pending


def get_review(session: Session, dataset_id: int, job_id: int) -> AnnotationImportReview:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return _review(session, dataset_id, job_id)[0]


def latest_review(session: Session, dataset_id: int) -> AnnotationImportReview | None:
    dataset_service.get_dataset_or_404(session, dataset_id)
    if "jobs" not in inspect(session.get_bind()).get_table_names():
        return None
    jobs = session.exec(select(Job).where(Job.dataset_id == dataset_id, Job.status == "succeeded",
        Job.job_type.in_(["annotation.import", "annotation.import.labelme"])).order_by(Job.id.desc())).all()
    for job in jobs:
        if not json.loads(job.result_json or "{}").get("review_available"):
            continue
        try:
            return get_review(session, dataset_id, job.id)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
    return None


def confirm_remaining(session: Session, dataset_id: int, job_id: int,
                      payload: AnnotationImportConfirmRequest) -> AnnotationImportReview:
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    try:
        review, pending = _review(session, dataset_id, job_id)
        if review.fingerprint != payload.expected_fingerprint:
            raise HTTPException(409, "本批标注或图片状态已变化，请刷新复查结果后重新确认。")
        annotations = annotation_service.annotations_by_sample(session, [sample.id for sample, safe in pending if safe])
        for sample, safe in pending:
            if not safe:
                continue
            sample.annotation_progress = "completed_with_objects" if annotations.get(sample.id) else "completed_empty"
            sample.review_status = "in_review"
            sample.updated_at = utc_now()
            session.add(sample)
        if review.confirmable:
            bump_dataset_revision(session, dataset_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_review(session, dataset_id, job_id)
