from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.job_runtime import job_runner
from app.schemas.triage_directory_mapping import (
    TriageDirectoryMappingJobCreateRequest,
    TriageDirectoryMappingJobCreateResponse,
    TriageDirectoryMappingPreviewRequest,
    TriageDirectoryMappingPreviewResponse,
    TriageDirectorySourceResponse,
)
from app.services import (
    job_service,
    triage_directory_mapping_job_service,
    triage_directory_mapping_service,
    triage_service,
)


router = APIRouter(prefix="/api", tags=["triage-directory-mapping"])


def _raise_mapping_error(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        triage_directory_mapping_service.TriageDirectoryMappingPlanNotFoundError,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(
        exc,
        (
            triage_directory_mapping_service.TriageDirectoryMappingPlanExpiredError,
            triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError,
            triage_service.TriageSchemaUnavailableError,
            job_service.JobSchemaUnavailableError,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    ) from exc


@router.get(
    "/datasets/{dataset_id}/triage-directory-sources",
    response_model=TriageDirectorySourceResponse,
)
def list_triage_source_directories(
    dataset_id: int,
    search: str | None = Query(default=None, max_length=300),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
) -> TriageDirectorySourceResponse:
    try:
        return triage_directory_mapping_service.list_triage_source_directories(
            session,
            dataset_id,
            search=search,
            page=page,
            page_size=page_size,
        )
    except (
        triage_directory_mapping_service.TriageDirectoryMappingError,
        triage_service.TriageError,
    ) as exc:
        _raise_mapping_error(exc)


@router.post(
    "/datasets/{dataset_id}/triage-directory-mapping-previews",
    response_model=TriageDirectoryMappingPreviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_triage_directory_mapping_preview(
    dataset_id: int,
    payload: TriageDirectoryMappingPreviewRequest,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
) -> TriageDirectoryMappingPreviewResponse:
    try:
        return triage_directory_mapping_service.create_triage_directory_mapping_preview(
            session,
            dataset_id,
            payload,
            page=page,
            page_size=page_size,
        )
    except (
        triage_directory_mapping_service.TriageDirectoryMappingError,
        triage_service.TriageError,
    ) as exc:
        _raise_mapping_error(exc)


@router.get(
    "/datasets/{dataset_id}/triage-directory-mapping-previews/{plan_id}",
    response_model=TriageDirectoryMappingPreviewResponse,
)
def get_triage_directory_mapping_preview(
    dataset_id: int,
    plan_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
) -> TriageDirectoryMappingPreviewResponse:
    try:
        return triage_directory_mapping_service.get_triage_directory_mapping_preview(
            dataset_id,
            plan_id,
            page=page,
            page_size=page_size,
        )
    except triage_directory_mapping_service.TriageDirectoryMappingError as exc:
        _raise_mapping_error(exc)


@router.post(
    "/datasets/{dataset_id}/triage-directory-mapping-jobs",
    response_model=TriageDirectoryMappingJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_triage_directory_mapping_job(
    dataset_id: int,
    payload: TriageDirectoryMappingJobCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> TriageDirectoryMappingJobCreateResponse:
    try:
        result = triage_directory_mapping_job_service.create_triage_directory_mapping_job(
            session,
            dataset_id,
            payload,
        )
    except (
        triage_directory_mapping_service.TriageDirectoryMappingError,
        job_service.JobError,
    ) as exc:
        _raise_mapping_error(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result
