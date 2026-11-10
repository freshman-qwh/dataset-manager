from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.batch_reception import (
    BatchReceptionPreviewRequest, BatchReceptionProfileRead, BatchReceptionProfileWrite,
)
from app.schemas.industrial import ConfirmationRead, FrozenPlanRead, PlanConfirmation
from app.services import batch_reception as service


router = APIRouter(prefix="/api/datasets/{dataset_id}/batch-reception", tags=["batch-reception"])


@router.get("/profile", response_model=BatchReceptionProfileRead)
def read_profile(dataset_id: int, session: Session = Depends(get_session)):
    return service.read_profile(session, dataset_id)


@router.put("/profile", response_model=BatchReceptionProfileRead)
def save_profile(dataset_id: int, payload: BatchReceptionProfileWrite, session: Session = Depends(get_session)):
    return service.save_profile(session, dataset_id, payload)


@router.post("/previews", response_model=FrozenPlanRead)
def preview_batch(dataset_id: int, payload: BatchReceptionPreviewRequest, session: Session = Depends(get_session)):
    return service.preview(session, dataset_id, payload)


@router.post("/previews/{plan_id}/confirm", response_model=ConfirmationRead)
def confirm_batch(dataset_id: int, plan_id: str, payload: PlanConfirmation, session: Session = Depends(get_session)):
    return service.confirm(session, dataset_id, plan_id, payload)
