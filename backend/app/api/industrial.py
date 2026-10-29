from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.industrial import AnomalyPreviewRequest, ConfirmationRead, FrozenPlanRead, GroupPreviewRequest, PlanConfirmation
from app.services import anomaly_protocol_service, capture_group_service, industrial_plan_service

router = APIRouter(prefix="/api/datasets/{dataset_id}/industrial", tags=["industrial"])


@router.post("/group-previews", response_model=FrozenPlanRead)
def preview_groups(dataset_id: int, payload: GroupPreviewRequest, session: Session = Depends(get_session)):
    return industrial_plan_service.page(capture_group_service.preview(session, dataset_id, payload))


@router.get("/plans/{plan_id}", response_model=FrozenPlanRead)
def read_plan(dataset_id: int, plan_id: str, page: int = Query(1, ge=1),
              page_size: int = Query(50, ge=1, le=200), session: Session = Depends(get_session)):
    return industrial_plan_service.page(industrial_plan_service.load(session, dataset_id, plan_id), page, page_size)


@router.post("/group-previews/{plan_id}/confirm", response_model=ConfirmationRead)
def confirm_groups(dataset_id: int, plan_id: str, payload: PlanConfirmation, session: Session = Depends(get_session)):
    return capture_group_service.confirm(session, dataset_id, plan_id, payload)


@router.post("/anomaly-previews", response_model=FrozenPlanRead)
def preview_anomaly(dataset_id: int, payload: AnomalyPreviewRequest, session: Session = Depends(get_session)):
    return industrial_plan_service.page(anomaly_protocol_service.preview(session, dataset_id, payload))


@router.post("/anomaly-previews/{plan_id}/confirm-splits", response_model=ConfirmationRead)
def confirm_anomaly_splits(dataset_id: int, plan_id: str, payload: PlanConfirmation, session: Session = Depends(get_session)):
    return anomaly_protocol_service.confirm_splits(session, dataset_id, plan_id, payload)
