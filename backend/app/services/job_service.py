from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, inspect
from sqlmodel import Session, select

from app.models.dataset import Dataset
from app.models.job import Job
from app.schemas.job import JobCreate, JobListResponse, JobRead, JobStatus


TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
MAX_JOB_JSON_BYTES = 64 * 1024
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "cancelled", "interrupted"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "interrupted": frozenset(),
}


class JobError(ValueError):
    """Base error for job state and persistence operations."""


class JobSchemaUnavailableError(JobError):
    """Raised when the database has not migrated to the jobs schema."""


class JobNotFoundError(JobError):
    """Raised when a requested job does not exist."""


class JobStateError(JobError):
    """Raised for an invalid state transition or progress update."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_jobs_schema(session: Session) -> None:
    if "jobs" not in inspect(session.get_bind()).get_table_names():
        raise JobSchemaUnavailableError(
            "The jobs schema is unavailable. Stop the backend and upgrade the database."
        )


def _decode_json(value: str | None) -> dict[str, object] | None:
    if value is None:
        return None
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def _encode_json(value: dict[str, object] | None) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_JOB_JSON_BYTES:
        raise JobStateError(
            f"Job JSON snapshots cannot exceed {MAX_JOB_JSON_BYTES} UTF-8 bytes."
        )
    return encoded


def to_job_read(job: Job) -> JobRead:
    if job.id is None:
        raise JobStateError("A persisted job must have an id.")
    return JobRead(
        id=job.id,
        job_type=job.job_type,
        title=job.title,
        status=job.status,
        dataset_id=job.dataset_id,
        stage=job.stage,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        error_count=job.error_count,
        attempt=job.attempt,
        parameters=_decode_json(job.parameters_json) or {},
        result=_decode_json(job.result_json),
        error=_decode_json(job.error_json),
        retry_of_id=job.retry_of_id,
        cancel_requested_at=job.cancel_requested_at,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


def create_job(session: Session, payload: JobCreate) -> JobRead:
    ensure_jobs_schema(session)
    if payload.dataset_id is not None and session.get(Dataset, payload.dataset_id) is None:
        raise JobError(f"Dataset {payload.dataset_id} does not exist.")
    job = Job(
        job_type=payload.job_type,
        title=payload.title,
        dataset_id=payload.dataset_id,
        progress_total=payload.progress_total,
        parameters_json=_encode_json(payload.parameters) or "{}",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return to_job_read(job)


def get_job_model(session: Session, job_id: int) -> Job:
    ensure_jobs_schema(session)
    job = session.get(Job, job_id)
    if job is None:
        raise JobNotFoundError(f"Job {job_id} does not exist.")
    return job


def get_job(session: Session, job_id: int) -> JobRead:
    return to_job_read(get_job_model(session, job_id))


def list_jobs(
    session: Session,
    *,
    status: JobStatus | None = None,
    job_type: str | None = None,
    dataset_id: int | None = None,
    limit: int = 100,
) -> JobListResponse:
    ensure_jobs_schema(session)
    filters = []
    if status is not None:
        filters.append(Job.status == status)
    if job_type is not None:
        filters.append(Job.job_type == job_type)
    if dataset_id is not None:
        filters.append(Job.dataset_id == dataset_id)

    statement = select(Job)
    count_statement = select(func.count(Job.id))
    for condition in filters:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    statement = statement.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
    jobs = list(session.exec(statement).all())
    total = int(session.exec(count_statement).one())
    return JobListResponse(items=[to_job_read(job) for job in jobs], total=total)


def find_active_job(
    session: Session,
    *,
    job_type: str,
    dataset_id: int | None,
    parameter_match: tuple[str, object] | None = None,
) -> JobRead | None:
    ensure_jobs_schema(session)
    jobs = session.exec(
        select(Job)
        .where(
            Job.job_type == job_type,
            Job.dataset_id == dataset_id,
            Job.status.in_(["queued", "running"]),
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
    ).all()
    for job in jobs:
        job_read = to_job_read(job)
        if parameter_match is None:
            return job_read
        key, expected = parameter_match
        if job_read.parameters.get(key) == expected:
            return job_read
    return None


def transition_job(
    session: Session,
    job_id: int,
    target_status: JobStatus,
    *,
    stage: str | None = None,
    result: dict[str, object] | None = None,
    error: dict[str, object] | None = None,
    error_count: int | None = None,
) -> JobRead:
    job = get_job_model(session, job_id)
    allowed = ALLOWED_TRANSITIONS.get(job.status, frozenset())
    if target_status not in allowed:
        raise JobStateError(
            f"Job {job_id} cannot transition from {job.status} to {target_status}."
        )
    if error_count is not None and error_count < 0:
        raise JobStateError("error_count cannot be negative.")
    encoded_result = _encode_json(result)
    encoded_error = _encode_json(error)

    now = utc_now()
    job.status = target_status
    job.updated_at = now
    if stage is not None:
        job.stage = stage
    if target_status == "running":
        job.started_at = now
        job.finished_at = None
    if target_status in TERMINAL_STATUSES:
        job.finished_at = now
    if encoded_result is not None:
        job.result_json = encoded_result
    if encoded_error is not None:
        job.error_json = encoded_error
    if error_count is not None:
        job.error_count = error_count

    session.add(job)
    session.commit()
    session.refresh(job)
    return to_job_read(job)


def update_job_progress(
    session: Session,
    job_id: int,
    *,
    current: int,
    total: int | None = None,
    stage: str | None = None,
    error_count: int | None = None,
) -> JobRead:
    job = get_job_model(session, job_id)
    if job.status != "running":
        raise JobStateError("Only a running job can report progress.")
    if current < 0 or total is not None and total < 0:
        raise JobStateError("Job progress cannot be negative.")
    effective_total = total if total is not None else job.progress_total
    if effective_total is not None and current > effective_total:
        raise JobStateError("Job progress cannot exceed its total.")
    if error_count is not None and error_count < 0:
        raise JobStateError("error_count cannot be negative.")

    job.progress_current = current
    if total is not None:
        job.progress_total = total
    if stage is not None:
        job.stage = stage
    if error_count is not None:
        job.error_count = error_count
    job.updated_at = utc_now()
    session.add(job)
    session.commit()
    session.refresh(job)
    return to_job_read(job)


def request_job_cancel(session: Session, job_id: int) -> JobRead:
    job = get_job_model(session, job_id)
    if job.status == "queued":
        return transition_job(
            session,
            job_id,
            "cancelled",
            stage="cancelled_before_start",
        )
    if job.status != "running":
        raise JobStateError("Only queued or running jobs can be cancelled.")
    if job.cancel_requested_at is None:
        job.cancel_requested_at = utc_now()
        job.updated_at = job.cancel_requested_at
        session.add(job)
        session.commit()
        session.refresh(job)
    return to_job_read(job)


def retry_job(session: Session, job_id: int) -> JobRead:
    source = get_job_model(session, job_id)
    if source.status not in {"failed", "cancelled", "interrupted"}:
        raise JobStateError("Only failed, cancelled, or interrupted jobs can be retried.")
    if source.id is None:
        raise JobStateError("A persisted job must have an id.")
    retry = Job(
        job_type=source.job_type,
        title=source.title,
        dataset_id=source.dataset_id,
        progress_total=source.progress_total,
        attempt=source.attempt + 1,
        parameters_json=source.parameters_json,
        retry_of_id=source.id,
    )
    session.add(retry)
    session.commit()
    session.refresh(retry)
    return to_job_read(retry)


def interrupt_running_jobs(session: Session) -> int:
    """Mark jobs abandoned by a previous process as explicitly interrupted."""
    ensure_jobs_schema(session)
    running_jobs = list(
        session.exec(select(Job).where(Job.status == "running")).all()
    )
    if not running_jobs:
        return 0

    now = utc_now()
    error_json = _encode_json(
        {
            "code": "process_restart",
            "message": "The backend stopped before this job reached a terminal state.",
        }
    )
    for job in running_jobs:
        job.status = "interrupted"
        job.stage = "process_stopped"
        job.error_json = error_json
        job.finished_at = now
        job.updated_at = now
        session.add(job)
    session.commit()
    return len(running_jobs)
