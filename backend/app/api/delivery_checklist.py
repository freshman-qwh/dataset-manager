from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.delivery_checklist import DeliveryChecklistRead, DeliveryChecklistRequest
from app.services.delivery_checklist import create_checklist


router = APIRouter(prefix="/api", tags=["delivery-checklist"])


@router.post("/datasets/{dataset_id}/delivery-checklist", response_model=DeliveryChecklistRead)
def read_delivery_checklist(
    dataset_id: int,
    payload: DeliveryChecklistRequest,
    session: Session = Depends(get_session),
) -> DeliveryChecklistRead:
    return create_checklist(session, dataset_id, payload)
