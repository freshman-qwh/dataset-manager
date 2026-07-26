from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.job_runtime import job_runner
from app.schemas.job import JobCreate, JobListResponse, JobRead, JobStatus
from app.services import job_service


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _raise_job_http_error(exc: job_service.JobError) -> NoReturn:
    if isinstance(exc, job_service.JobSchemaUnavailableError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, job_service.JobNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    ) from exc


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    session: Session = Depends(get_session),
) -> JobRead:
    try:
        created = job_service.create_job(session, payload)
    except job_service.JobError as exc:
        _raise_job_http_error(exc)
    job_runner.notify()
    return created


@router.get("", response_model=JobListResponse)
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    job_type: str | None = Query(default=None, max_length=80),
    dataset_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
) -> JobListResponse:
    try:
        return job_service.list_jobs(
            session,
            status=status_filter,
            job_type=job_type,
            dataset_id=dataset_id,
            limit=limit,
        )
    except job_service.JobError as exc:
        _raise_job_http_error(exc)


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: int,
    session: Session = Depends(get_session),
) -> JobRead:
    try:
        return job_service.get_job(session, job_id)
    except job_service.JobError as exc:
        _raise_job_http_error(exc)


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: int,
    session: Session = Depends(get_session),
) -> JobRead:
    try:
        return job_service.request_job_cancel(session, job_id)
    except job_service.JobError as exc:
        _raise_job_http_error(exc)


@router.post(
    "/{job_id}/retry",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def retry_job(
    job_id: int,
    session: Session = Depends(get_session),
) -> JobRead:
    try:
        retried = job_service.retry_job(session, job_id)
    except job_service.JobError as exc:
        _raise_job_http_error(exc)
    job_runner.notify()
    return retried
