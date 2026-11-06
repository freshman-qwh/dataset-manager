from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.comparison import ComparisonRead
from app.services.comparison_service import read_comparison

router = APIRouter(prefix="/api", tags=["comparison"])


@router.get("/datasets/{dataset_id}/comparison", response_model=ComparisonRead)
def get_comparison(
    dataset_id: int,
    category_id: int | None = Query(default=None, ge=1),
    batch_id: int | None = Query(default=None, ge=1),
    normal_page: int = Query(default=1, ge=1),
    anomaly_page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=24),
    session: Session = Depends(get_session),
) -> ComparisonRead:
    return read_comparison(session, dataset_id, category_id=category_id, batch_id=batch_id,
        normal_page=normal_page, anomaly_page=anomaly_page, page_size=page_size)
