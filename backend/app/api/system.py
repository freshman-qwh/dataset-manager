from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.core.job_runtime import job_runner
from app.schemas.database_integrity import (
    DatabaseIntegrityReport,
    DatabaseRepairPreview,
    DatabaseRepairPreviewRequest,
    DatabaseRepairRequest,
    DatabaseRepairResult,
)
from app.schemas.database_backup import DatabaseBackupJobCreateResponse
from app.schemas.thumbnail import ThumbnailMaintenanceJobCreateResponse
from app.services import (
    database_backup_service,
    database_integrity_service,
    job_service,
    thumbnail_maintenance_service,
)


router = APIRouter(prefix="/api/system", tags=["system"])


@router.post(
    "/database-backup-jobs",
    response_model=DatabaseBackupJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_database_backup_job(
    response: Response,
    session: Session = Depends(get_session),
) -> DatabaseBackupJobCreateResponse:
    try:
        result = database_backup_service.create_database_backup_job(session)
    except job_service.JobSchemaUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except job_service.JobError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result


@router.post(
    "/thumbnail-cache/maintenance-jobs",
    response_model=ThumbnailMaintenanceJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_thumbnail_cache_maintenance_job(
    response: Response,
    force: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> ThumbnailMaintenanceJobCreateResponse:
    try:
        result = thumbnail_maintenance_service.create_thumbnail_maintenance_job(
            session,
            force=force,
        )
    except job_service.JobSchemaUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    if result.job is not None:
        job_runner.notify()
    return result


@router.get("/database-integrity", response_model=DatabaseIntegrityReport)
def database_integrity_report(
    session: Session = Depends(get_session),
) -> DatabaseIntegrityReport:
    database_path = get_settings().database_path
    return database_integrity_service.build_integrity_report(
        session,
        database_name=database_path.name,
    )


@router.post(
    "/database-integrity/repair-preview",
    response_model=DatabaseRepairPreview,
)
def database_integrity_repair_preview(
    payload: DatabaseRepairPreviewRequest,
    session: Session = Depends(get_session),
) -> DatabaseRepairPreview:
    database_path = get_settings().database_path
    report = database_integrity_service.build_integrity_report(
        session,
        database_name=database_path.name,
    )
    try:
        return database_integrity_service.build_repair_preview(
            report,
            payload.action_ids,
        )
    except database_integrity_service.DatabaseIntegrityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except database_integrity_service.DatabaseIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post(
    "/database-integrity/repair",
    response_model=DatabaseRepairResult,
)
def database_integrity_repair(
    payload: DatabaseRepairRequest,
    session: Session = Depends(get_session),
) -> DatabaseRepairResult:
    database_path = get_settings().database_path
    try:
        return database_integrity_service.repair_integrity(
            session,
            database_path=database_path,
            report_token=payload.report_token,
            action_ids=payload.action_ids,
            confirmation=payload.confirmation,
        )
    except database_integrity_service.DatabaseIntegrityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except database_integrity_service.DatabaseIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
