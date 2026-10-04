from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.sam import SamPredictRequest, SamPrediction, SamStatus
from app.services.sam_service import predict_sample, sam_service

router = APIRouter(prefix="/api", tags=["sam"])


@router.get("/sam/status", response_model=SamStatus)
def get_sam_status() -> SamStatus:
    return sam_service.status()


@router.post("/samples/{sample_id}/sam/predict", response_model=SamPrediction)
def predict_sam_contour(sample_id: int, payload: SamPredictRequest,
                        session: Session = Depends(get_session)) -> SamPrediction:
    return predict_sample(session, sample_id, payload)
