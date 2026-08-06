import json
import math
from pathlib import Path

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.annotation import Annotation
from app.models.annotation_class import AnnotationClass
from app.models.dataset import utc_now
from app.schemas.annotation import AnnotationCreate, AnnotationRead, AnnotationReplaceRequest, AnnotationTagSyncResult
from app.services import annotation_class_service, sample_service
from app.services.annotation_geometry import points_within_image, polygon_area
from app.utils.image_size import read_image_size

SHAPE_TYPES = {"rectangle", "polygon", "point", "points"}


def to_annotation_read(annotation: Annotation) -> AnnotationRead:
    return AnnotationRead(
        id=annotation.id or 0,
        sample_id=annotation.sample_id,
        dataset_id=annotation.dataset_id,
        class_id=annotation.class_id,
        label=annotation.label,
        shape_type=annotation.shape_type,
        points=_loads_list(annotation.points_json),
        flags=_loads_dict(annotation.flags_json),
        attributes=_loads_dict(annotation.attributes_json),
        group_id=annotation.group_id,
        z_order=annotation.z_order,
        locked=annotation.locked,
        hidden=annotation.hidden,
        source=annotation.source,
        notes=annotation.notes,
        created_at=annotation.created_at,
        updated_at=annotation.updated_at,
    )


def list_sample_annotations(session: Session, sample_id: int) -> list[AnnotationRead]:
    sample = sample_service.get_sample_or_404(session, sample_id)
    statement = (
        select(Annotation)
        .where(Annotation.sample_id == sample.id)
        .order_by(Annotation.z_order, Annotation.id)
    )
    return [to_annotation_read(item) for item in session.exec(statement).all()]


def replace_sample_annotations(
    session: Session,
    sample_id: int,
    payload: AnnotationReplaceRequest,
    *,
    commit: bool = True,
) -> list[AnnotationRead]:
    sample = sample_service.get_sample_or_404(session, sample_id)
    if sample.file_type != "image":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image samples can be annotated.")
    if payload.save_mode == "confirm_empty" and payload.annotations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirm_empty requires an empty annotation list.",
        )
    if payload.save_mode == "complete" and not payload.annotations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="complete requires at least one annotation; use confirm_empty for a negative sample.",
        )

    for item in payload.annotations:
        _validate_annotation(item)

    image_size = read_image_size(Path(sample.absolute_path))
    if image_size is not None:
        for item in payload.annotations:
            if not points_within_image(item.points, image_size[0], image_size[1]):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Annotation coordinates must stay within image bounds.",
                )

    old_items = session.exec(select(Annotation).where(Annotation.sample_id == sample_id)).all()
    for item in old_items:
        session.delete(item)

    now = utc_now()
    created: list[Annotation] = []
    for index, item in enumerate(payload.annotations):
        annotation_class = _resolve_annotation_class(session, sample.dataset_id, item)
        annotation = Annotation(
            sample_id=sample.id or 0,
            dataset_id=sample.dataset_id,
            class_id=annotation_class.id,
            tag_id=None,
            label=item.label.strip(),
            shape_type=item.shape_type,
            points_json=json.dumps(item.points),
            flags_json=json.dumps(item.flags, ensure_ascii=False),
            attributes_json=json.dumps(item.attributes, ensure_ascii=False),
            group_id=item.group_id,
            z_order=item.z_order if item.z_order is not None else index,
            locked=item.locked,
            hidden=item.hidden,
            source=item.source.strip() or "manual",
            notes=item.notes,
            created_at=now,
            updated_at=now,
        )
        session.add(annotation)
        created.append(annotation)

    if payload.review_status is not None:
        sample.review_status = _validate_review_status(payload.review_status)
    elif payload.save_mode in {"complete", "confirm_empty"} and sample.review_status == "not_reviewed":
        sample.review_status = "in_review"
    if payload.save_mode == "complete":
        sample.annotation_progress = "completed_with_objects"
    elif payload.save_mode == "confirm_empty":
        sample.annotation_progress = "completed_empty"
    else:
        sample.annotation_progress = "in_progress"
    sample.updated_at = now
    session.add(sample)
    if commit:
        session.commit()
        for item in created:
            session.refresh(item)
    else:
        session.flush()
    return [to_annotation_read(item) for item in created]


def sync_annotation_classes_to_sample_tags(
    session: Session,
    sample_id: int,
    *,
    commit: bool = True,
) -> AnnotationTagSyncResult:
    sample = sample_service.get_sample_or_404(session, sample_id)
    annotations = session.exec(
        select(Annotation).where(Annotation.sample_id == sample_id).order_by(Annotation.z_order, Annotation.id)
    ).all()
    labels: list[str] = []
    seen_labels: set[str] = set()
    for annotation in annotations:
        label = annotation.label.strip()
        key = label.casefold()
        if label and key not in seen_labels:
            seen_labels.add(key)
            labels.append(label)

    existing_keys = {tag.name.casefold() for tag in sample.tags}
    existing_tags = [label for label in labels if label.casefold() in existing_keys]
    added_tags = [label for label in labels if label.casefold() not in existing_keys]
    for label in added_tags:
        sample.tags.append(sample_service._get_or_create_tag(session, sample.dataset_id, label))
    sample.updated_at = utc_now()
    session.add(sample)
    if commit:
        session.commit()
    else:
        session.flush()
    return AnnotationTagSyncResult(
        sample_id=sample.id or 0,
        added_tags=added_tags,
        existing_tags=existing_tags,
    )


def delete_sample_annotations(session: Session, sample_ids: list[int]) -> None:
    if not sample_ids:
        return
    annotations = session.exec(select(Annotation).where(Annotation.sample_id.in_(sample_ids))).all()
    for annotation in annotations:
        session.delete(annotation)


def annotations_by_sample(session: Session, sample_ids: list[int]) -> dict[int, list[AnnotationRead]]:
    if not sample_ids:
        return {}
    annotations = session.exec(
        select(Annotation)
        .where(Annotation.sample_id.in_(sample_ids))
        .order_by(Annotation.sample_id, Annotation.z_order, Annotation.id)
    ).all()
    result: dict[int, list[AnnotationRead]] = {}
    for annotation in annotations:
        result.setdefault(annotation.sample_id, []).append(to_annotation_read(annotation))
    return result


def export_labelme_annotation(session: Session, sample_id: int) -> dict[str, object]:
    sample = sample_service.get_sample_or_404(session, sample_id)
    annotations = list_sample_annotations(session, sample_id)
    size = read_image_size(Path(sample.absolute_path))
    width = size[0] if size else None
    height = size[1] if size else None
    return {
        "version": "dataset-manager",
        "flags": {},
        "shapes": [_to_labelme_shape(annotation) for annotation in annotations],
        "imagePath": sample.relative_path,
        "imageData": None,
        "imageHeight": height,
        "imageWidth": width,
    }


def validate_annotation(item: AnnotationCreate) -> None:
    _validate_annotation(item)


def _to_labelme_shape(annotation: AnnotationRead) -> dict[str, object]:
    flags = dict(annotation.flags)
    for key in ("occluded", "truncated", "difficult"):
        if key in annotation.attributes:
            flags[key] = bool(annotation.attributes[key])
    return {
        "label": annotation.label,
        "points": _paired_points(annotation.points),
        "group_id": annotation.group_id,
        "description": annotation.notes or "",
        "shape_type": annotation.shape_type,
        "flags": flags,
    }


def _resolve_annotation_class(session: Session, dataset_id: int, item: AnnotationCreate) -> AnnotationClass:
    label = item.label.strip()
    if item.class_id is not None:
        annotation_class = session.get(AnnotationClass, item.class_id)
        if not annotation_class or annotation_class.dataset_id != dataset_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Annotation class must belong to the same dataset.",
            )
        if annotation_class.name.casefold() != label.casefold():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Annotation label does not match the selected annotation class.",
            )
        return annotation_class
    return annotation_class_service.get_or_create_annotation_class(session, dataset_id, label)


def _validate_annotation(item: AnnotationCreate) -> None:
    label = item.label.strip()
    if not label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Annotation label is required.")
    if item.shape_type not in SHAPE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported shape type: {item.shape_type}")
    if any(not math.isfinite(value) or value < 0 for value in item.points):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Annotation points must be finite positive coordinates.")
    if item.shape_type == "rectangle":
        if len(item.points) != 4:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rectangle annotations require 4 coordinates.")
        xtl, ytl, xbr, ybr = item.points
        if xbr <= xtl or ybr <= ytl:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rectangle coordinates must have positive width and height.")
    elif item.shape_type == "polygon":
        if len(item.points) < 6 or len(item.points) % 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Polygon annotations require at least 3 points.")
        if polygon_area(item.points) <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Polygon annotations require positive area.")
    elif item.shape_type == "point":
        if len(item.points) != 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Point annotations require exactly 2 coordinates.")
    elif item.shape_type == "points" and (len(item.points) < 2 or len(item.points) % 2):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Points annotations require coordinate pairs.")


def _validate_review_status(value: str) -> str:
    normalized = value.strip() or "not_reviewed"
    if normalized not in sample_service.REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported review_status: {value}",
        )
    return normalized


def _loads_dict(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_list(value: str | None) -> list[float]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[float] = []
    for item in parsed:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            continue
    return result


def _paired_points(points: list[float]) -> list[list[float]]:
    return [[points[index], points[index + 1]] for index in range(0, len(points) - 1, 2)]
