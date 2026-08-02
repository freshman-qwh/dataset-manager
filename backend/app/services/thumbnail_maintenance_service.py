from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from app.core.config import get_settings
from app.schemas.job import JobCreate
from app.schemas.thumbnail import ThumbnailMaintenanceJobCreateResponse
from app.services import job_service, thumbnail_cache_service
from app.services.job_runner import JobContext
from app.services.thumbnail_service import thumbnail_cache_root


THUMBNAIL_MAINTENANCE_JOB_TYPE = "thumbnail.maintain"
MAINTENANCE_MARKER_NAME = ".maintenance-completed"


def _maintenance_marker() -> Path:
    return thumbnail_cache_root() / MAINTENANCE_MARKER_NAME


def maintenance_is_due(*, now_timestamp: float | None = None) -> bool:
    marker = _maintenance_marker()
    if not marker.is_file():
        return True
    now = now_timestamp if now_timestamp is not None else time.time()
    try:
        age = now - marker.stat().st_mtime
    except OSError:
        return True
    return age >= get_settings().thumbnail_cache_maintenance_interval_seconds


def create_thumbnail_maintenance_job(
    session: Session,
    *,
    force: bool,
) -> ThumbnailMaintenanceJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    due = force or maintenance_is_due()
    if not due:
        return ThumbnailMaintenanceJobCreateResponse(job=None, created=False, due=False)

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=THUMBNAIL_MAINTENANCE_JOB_TYPE,
        dataset_id=None,
    )
    if active is not None:
        session.commit()
        return ThumbnailMaintenanceJobCreateResponse(job=active, created=False, due=True)

    created = job_service.create_job(
        session,
        JobCreate(
            job_type=THUMBNAIL_MAINTENANCE_JOB_TYPE,
            title="维护缩略图缓存",
            parameters={
                "max_bytes": get_settings().thumbnail_cache_max_bytes,
            },
        ),
    )
    return ThumbnailMaintenanceJobCreateResponse(job=created, created=True, due=True)


def run_thumbnail_maintenance_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    max_bytes = parameters.get("max_bytes")
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        raise job_service.JobStateError(
            "A thumbnail.maintain job requires a positive max_bytes snapshot."
        )
    context.report_progress(current=0, stage="scanning_thumbnail_cache")
    with Session(context.engine) as session:
        result = thumbnail_cache_service.maintain_thumbnail_cache(
            session,
            max_bytes=max_bytes,
            checkpoint=context.checkpoint,
            progress=lambda current, total: context.report_progress(
                current=current,
                total=total,
                stage="scanning_thumbnail_cache",
            ),
            prune_started=lambda current, total: context.report_progress(
                current=current,
                total=total,
                stage="pruning_thumbnail_cache",
            ),
        )
    context.checkpoint()
    if result.get("error_count") == 0:
        marker = _maintenance_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    return result
