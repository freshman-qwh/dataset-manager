from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.dataset_card import DatasetCardRead
from app.services.dataset_card_service import read_dataset_card

router = APIRouter(prefix="/api", tags=["dataset-card"])


@router.get("/datasets/{dataset_id}/card", response_model=DatasetCardRead)
def get_dataset_card(dataset_id: int, session: Session = Depends(get_session)) -> DatasetCardRead:
    return read_dataset_card(session, dataset_id)
