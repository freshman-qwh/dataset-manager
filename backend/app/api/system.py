from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.schemas.database_integrity import (
    DatabaseIntegrityReport,
    DatabaseRepairPreview,
    DatabaseRepairPreviewRequest,
    DatabaseRepairRequest,
    DatabaseRepairResult,
)
from app.services import database_integrity_service


router = APIRouter(prefix="/api/system", tags=["system"])


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
