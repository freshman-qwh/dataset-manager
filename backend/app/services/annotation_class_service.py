from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.annotation import Annotation
from app.models.annotation_class import AnnotationClass
from app.models.dataset import utc_now
from app.schemas.annotation_class import AnnotationClassCreate, AnnotationClassRead, AnnotationClassUpdate
from app.services.dataset_service import get_dataset_or_404
from app.services.dataset_revision_service import bump_dataset_revision


def list_annotation_classes(session: Session, dataset_id: int) -> list[AnnotationClassRead]:
    get_dataset_or_404(session, dataset_id)
    items = session.exec(
        select(AnnotationClass).where(AnnotationClass.dataset_id == dataset_id).order_by(AnnotationClass.name)
    ).all()
    return [AnnotationClassRead.model_validate(item) for item in items]


def get_or_create_annotation_class(
    session: Session,
    dataset_id: int,
    name: str,
) -> AnnotationClass:
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Annotation class name is required.")
    items = session.exec(select(AnnotationClass).where(AnnotationClass.dataset_id == dataset_id)).all()
    existing = next((item for item in items if item.name.casefold() == clean_name.casefold()), None)
    if existing:
        return existing
    item = AnnotationClass(dataset_id=dataset_id, name=clean_name)
    session.add(item)
    session.flush()
    return item


def create_annotation_class(
    session: Session,
    dataset_id: int,
    payload: AnnotationClassCreate,
) -> AnnotationClassRead:
    get_dataset_or_404(session, dataset_id)
    item = AnnotationClass(
        dataset_id=dataset_id,
        name=payload.name.strip(),
        color=payload.color,
        description=payload.description,
    )
    session.add(item)
    bump_dataset_revision(session, dataset_id)
    _commit_or_conflict(session)
    session.refresh(item)
    return AnnotationClassRead.model_validate(item)


def update_annotation_class(
    session: Session,
    class_id: int,
    payload: AnnotationClassUpdate,
) -> AnnotationClassRead:
    item = _get_or_404(session, class_id)
    updates = payload.model_dump(exclude_unset=True)
    old_name = item.name
    if "name" in updates and updates["name"] is not None:
        item.name = updates["name"].strip()
    if "color" in updates:
        item.color = updates["color"]
    if "description" in updates:
        item.description = updates["description"]
    item.updated_at = utc_now()
    session.add(item)
    if item.name != old_name:
        annotations = session.exec(select(Annotation).where(Annotation.class_id == item.id)).all()
        for annotation in annotations:
            annotation.label = item.name
            annotation.updated_at = utc_now()
            session.add(annotation)
    bump_dataset_revision(session, item.dataset_id)
    _commit_or_conflict(session)
    session.refresh(item)
    return AnnotationClassRead.model_validate(item)


def delete_annotation_class(session: Session, class_id: int) -> None:
    item = _get_or_404(session, class_id)
    dataset_id = item.dataset_id
    annotations = session.exec(select(Annotation).where(Annotation.class_id == item.id)).all()
    for annotation in annotations:
        annotation.class_id = None
        session.add(annotation)
    session.delete(item)
    bump_dataset_revision(session, dataset_id)
    session.commit()


def _get_or_404(session: Session, class_id: int) -> AnnotationClass:
    item = session.get(AnnotationClass, class_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Annotation class {class_id} was not found.")
    return item


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Annotation class already exists.") from exc
