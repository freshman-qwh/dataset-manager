from fastapi import APIRouter, Depends, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.annotation_class import AnnotationClassCreate, AnnotationClassRead, AnnotationClassUpdate
from app.services import annotation_class_service

router = APIRouter(prefix="/api", tags=["annotation-classes"])


@router.get("/datasets/{dataset_id}/annotation-classes", response_model=list[AnnotationClassRead])
def list_annotation_classes(dataset_id: int, session: Session = Depends(get_session)) -> list[AnnotationClassRead]:
    return annotation_class_service.list_annotation_classes(session, dataset_id)


@router.post(
    "/datasets/{dataset_id}/annotation-classes",
    response_model=AnnotationClassRead,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation_class(
    dataset_id: int,
    payload: AnnotationClassCreate,
    session: Session = Depends(get_session),
) -> AnnotationClassRead:
    return annotation_class_service.create_annotation_class(session, dataset_id, payload)


@router.patch("/annotation-classes/{class_id}", response_model=AnnotationClassRead)
def update_annotation_class(
    class_id: int,
    payload: AnnotationClassUpdate,
    session: Session = Depends(get_session),
) -> AnnotationClassRead:
    return annotation_class_service.update_annotation_class(session, class_id, payload)


@router.delete("/annotation-classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation_class(class_id: int, session: Session = Depends(get_session)) -> Response:
    annotation_class_service.delete_annotation_class(session, class_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
