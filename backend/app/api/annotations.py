from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.annotation import AnnotationRead, AnnotationReplaceRequest, AnnotationTagSyncResult
from app.services import annotation_service

router = APIRouter(prefix="/api", tags=["annotations"])


@router.get("/samples/{sample_id}/annotations", response_model=list[AnnotationRead])
def list_sample_annotations(sample_id: int, session: Session = Depends(get_session)) -> list[AnnotationRead]:
    return annotation_service.list_sample_annotations(session, sample_id)


@router.put("/samples/{sample_id}/annotations", response_model=list[AnnotationRead])
def replace_sample_annotations(
    sample_id: int,
    payload: AnnotationReplaceRequest,
    session: Session = Depends(get_session),
) -> list[AnnotationRead]:
    return annotation_service.replace_sample_annotations(session, sample_id, payload)


@router.post(
    "/samples/{sample_id}/annotations/sync-sample-tags",
    response_model=AnnotationTagSyncResult,
)
def sync_annotation_classes_to_sample_tags(
    sample_id: int,
    session: Session = Depends(get_session),
) -> AnnotationTagSyncResult:
    return annotation_service.sync_annotation_classes_to_sample_tags(session, sample_id)


@router.post("/samples/{sample_id}/annotations/export-labelme")
def export_labelme_annotation(sample_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return annotation_service.export_labelme_annotation(session, sample_id)
