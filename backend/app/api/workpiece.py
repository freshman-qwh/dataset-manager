from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.workpiece import WorkpieceViewsRead
from app.services.workpiece import read_workpiece_views


router = APIRouter(prefix="/api", tags=["workpiece"])


@router.get("/samples/{sample_id}/workpiece-views", response_model=WorkpieceViewsRead)
def get_workpiece_views(
    sample_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=24),
    session: Session = Depends(get_session),
) -> WorkpieceViewsRead:
    return read_workpiece_views(session, sample_id, page=page, page_size=page_size)
