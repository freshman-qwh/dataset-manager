from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.job import JobCreate
from app.schemas.thumbnail import ThumbnailJobCreateResponse, ThumbnailJobRequest
from app.services import dataset_service, job_service, thumbnail_service
from app.services.job_runner import JobCancelled, JobContext, JobInterrupted


THUMBNAIL_JOB_TYPE = "thumbnail.generate"


def _eligible_samples(
    session: Session,
    dataset_id: int,
    sample_ids: list[int],
) -> list[Sample]:
    if not sample_ids:
        return []
    return list(
        session.exec(
            select(Sample)
            .where(
                Sample.dataset_id == dataset_id,
                Sample.id.in_(sample_ids),
                Sample.file_type == "image",
                Sample.file_status == "normal",
            )
            .order_by(Sample.id.asc())
        ).all()
    )


def create_thumbnail_job(
    session: Session,
    dataset_id: int,
    payload: ThumbnailJobRequest,
) -> ThumbnailJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    sample_ids = list(dict.fromkeys(payload.sample_ids))
    eligible = _eligible_samples(session, dataset_id, sample_ids)
    items = [
        {"sample_id": sample.id, "file_hash": sample.file_hash}
        for sample in eligible
        if sample.id is not None
    ]
    cached_count = sum(
        1 for item in items if thumbnail_service.is_thumbnail_cached(str(item["file_hash"]))
    )
    response_counts = {
        "requested_count": len(sample_ids),
        "eligible_count": len(items),
        "cached_count": cached_count,
        "skipped_count": len(sample_ids) - len(items),
    }
    if not items or cached_count == len(items):
        return ThumbnailJobCreateResponse(job=None, created=False, **response_counts)

    fingerprint_payload = {
        "items": items,
        "spec_version": thumbnail_service.THUMBNAIL_SPEC_VERSION,
    }
    request_fingerprint = sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    parameters = {**fingerprint_payload, "request_fingerprint": request_fingerprint}

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=THUMBNAIL_JOB_TYPE,
        dataset_id=dataset_id,
        parameter_match=("request_fingerprint", request_fingerprint),
    )
    if active is not None:
        session.commit()
        return ThumbnailJobCreateResponse(
            job=active,
            created=False,
            **response_counts,
        )

    unique_content_count = len({str(item["file_hash"]) for item in items})
    created = job_service.create_job(
        session,
        JobCreate(
            job_type=THUMBNAIL_JOB_TYPE,
            title=f"生成缩略图：{dataset.name}",
            dataset_id=dataset_id,
            parameters=parameters,
            progress_total=unique_content_count,
        ),
    )
    return ThumbnailJobCreateResponse(job=created, created=True, **response_counts)


def _job_candidates(
    session: Session,
    dataset_id: int,
    items: list[dict[str, object]],
) -> tuple[list[thumbnail_service.ThumbnailCandidate], int]:
    frozen = {
        int(item["sample_id"]): str(item["file_hash"])
        for item in items
        if isinstance(item.get("sample_id"), int)
        and isinstance(item.get("file_hash"), str)
    }
    samples = _eligible_samples(session, dataset_id, list(frozen))
    candidates_by_hash: dict[str, thumbnail_service.ThumbnailCandidate] = {}
    stale_count = 0
    for sample in samples:
        if sample.id is None or frozen.get(sample.id) != sample.file_hash:
            stale_count += 1
            continue
        candidates_by_hash.setdefault(
            sample.file_hash,
            thumbnail_service.ThumbnailCandidate(
                sample_id=sample.id,
                path=Path(sample.absolute_path),
                file_hash=sample.file_hash,
                file_size=sample.file_size,
                file_modified_at=sample.file_modified_at,
            ),
        )
    stale_count += len(frozen) - len(samples)
    return list(candidates_by_hash.values()), stale_count


def run_thumbnail_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    items = parameters.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise job_service.JobStateError("A thumbnail.generate job requires frozen items.")

    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id is None:
            raise job_service.JobStateError(
                "A thumbnail.generate job requires dataset_id."
            )
        candidates, snapshot_stale_count = _job_candidates(
            session,
            job.dataset_id,
            items,
        )

    context.report_progress(
        current=0,
        total=len(candidates),
        stage="generating_thumbnails",
        error_count=0,
    )
    try:
        result = thumbnail_service.generate_thumbnail_batch(
            candidates,
            checkpoint=context.checkpoint,
            progress=lambda current, total, error_count: context.report_progress(
                current=current,
                total=total,
                stage="generating_thumbnails",
                error_count=error_count,
            ),
        )
    except thumbnail_service.ThumbnailGenerationStopped as stopped:
        partial_result = {
            **stopped.result,
            "requested_sample_count": len(items),
            "snapshot_stale_count": snapshot_stale_count,
        }
        if isinstance(stopped.__cause__, JobCancelled):
            raise JobCancelled(str(stopped.__cause__), result=partial_result) from stopped
        if isinstance(stopped.__cause__, JobInterrupted):
            raise JobInterrupted(str(stopped.__cause__), result=partial_result) from stopped
        raise stopped.__cause__ from stopped

    return {
        **result,
        "requested_sample_count": len(items),
        "snapshot_stale_count": snapshot_stale_count,
    }
