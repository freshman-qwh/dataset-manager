from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.core.database import get_session
from app.core.job_runtime import job_runner
from app.schemas.job import JobCreate, JobListResponse, JobRead, JobStatus
from app.schemas.annotation_import import AnnotationImportRollbackJobCreateResponse, LabelmeImportRollbackJobCreateResponse
from app.schemas.metadata_import import MetadataImportRollbackJobCreateResponse
from app.services import annotation_import_job_service, job_artifact_service, job_service, metadata_import_job_service


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


@router.get("/{job_id}/artifact")
def download_job_artifact(
    job_id: int,
    session: Session = Depends(get_session),
) -> FileResponse:
    try:
        job = job_service.get_job(session, job_id)
    except job_service.JobError as exc:
        _raise_job_http_error(exc)
    if job.status != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The job artifact is available only after successful completion.",
        )
    artifact = job.result.get("artifact") if job.result else None
    if not isinstance(artifact, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The job does not have a downloadable artifact.",
        )
    filename = artifact.get("filename")
    media_type = artifact.get("media_type")
    if not isinstance(filename, str) or not isinstance(media_type, str):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The job artifact metadata is incomplete.",
        )
    try:
        path = job_artifact_service.resolve_job_artifact(
            job_artifact_service.job_artifact_root(),
            job_id=job_id,
            filename=filename,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The job artifact metadata is invalid.",
        ) from exc
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The job artifact is no longer available.",
        )
    return FileResponse(path, media_type=media_type, filename=filename)


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


@router.post(
    "/{job_id}/metadata-import-rollback-jobs",
    response_model=MetadataImportRollbackJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_metadata_import_rollback_job(
    job_id: int,
    response: Response,
    session: Session = Depends(get_session),
) -> MetadataImportRollbackJobCreateResponse:
    try:
        result = metadata_import_job_service.create_metadata_import_rollback_job(
            session,
            job_id,
        )
    except job_service.JobError as exc:
        _raise_job_http_error(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result


@router.post(
    "/{job_id}/annotation-import-labelme-rollback-jobs",
    response_model=LabelmeImportRollbackJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_labelme_import_rollback_job(
    job_id: int,
    response: Response,
    session: Session = Depends(get_session),
) -> LabelmeImportRollbackJobCreateResponse:
    try:
        result = annotation_import_job_service.create_labelme_import_rollback_job(session, job_id)
    except job_service.JobError as exc:
        _raise_job_http_error(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result


@router.post(
    "/{job_id}/annotation-import-rollback-jobs",
    response_model=AnnotationImportRollbackJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation_import_rollback_job(
    job_id: int,
    response: Response,
    session: Session = Depends(get_session),
) -> AnnotationImportRollbackJobCreateResponse:
    try:
        result = annotation_import_job_service.create_annotation_import_rollback_job(session, job_id)
    except job_service.JobError as exc:
        _raise_job_http_error(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result
