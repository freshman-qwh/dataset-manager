from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.job_runtime import job_runner
from app.schemas.directory_export import (
    DirectoryExportJobCreateRequest,
    DirectoryExportJobCreateResponse,
    DirectoryExportPreviewRequest,
    DirectoryExportPreviewResponse,
)
from app.services import (
    directory_export_job_service,
    directory_export_service,
    job_service,
    triage_service,
)


router = APIRouter(prefix="/api", tags=["directory-exports"])


def _raise_export_error(exc: Exception) -> NoReturn:
    if isinstance(exc, directory_export_service.DirectoryExportPlanNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(
        exc,
        (
            directory_export_service.DirectoryExportPlanExpiredError,
            directory_export_service.DirectoryExportPlanChangedError,
            job_service.JobSchemaUnavailableError,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    ) from exc


@router.post(
    "/datasets/{dataset_id}/directory-export-previews",
    response_model=DirectoryExportPreviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_directory_export_preview(
    dataset_id: int,
    payload: DirectoryExportPreviewRequest,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
) -> DirectoryExportPreviewResponse:
    try:
        return directory_export_service.create_directory_export_preview(
            session,
            dataset_id,
            payload,
            page=page,
            page_size=page_size,
        )
    except (
        directory_export_service.DirectoryExportError,
        triage_service.TriageError,
    ) as exc:
        _raise_export_error(exc)


@router.get(
    "/datasets/{dataset_id}/directory-export-previews/{plan_id}",
    response_model=DirectoryExportPreviewResponse,
)
def get_directory_export_preview(
    dataset_id: int,
    plan_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
) -> DirectoryExportPreviewResponse:
    try:
        return directory_export_service.get_directory_export_preview(
            dataset_id,
            plan_id,
            page=page,
            page_size=page_size,
        )
    except directory_export_service.DirectoryExportError as exc:
        _raise_export_error(exc)


@router.post(
    "/datasets/{dataset_id}/directory-export-jobs",
    response_model=DirectoryExportJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_directory_export_job(
    dataset_id: int,
    payload: DirectoryExportJobCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> DirectoryExportJobCreateResponse:
    try:
        result = directory_export_job_service.create_directory_export_job(
            session,
            dataset_id,
            payload,
        )
    except (
        directory_export_service.DirectoryExportError,
        job_service.JobError,
    ) as exc:
        _raise_export_error(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result
