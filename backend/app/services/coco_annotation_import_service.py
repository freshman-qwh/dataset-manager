from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.annotation import AnnotationCreate
from app.schemas.annotation_import import AnnotationImportRequest, LabelmeImportIssue
from app.services import annotation_import_service, annotation_service, dataset_service
from app.utils.image_size import read_image_size
from app.utils.paths import resolve_local_path


def prepare_coco_import(
    session: Session,
    dataset_id: int,
    payload: AnnotationImportRequest,
) -> annotation_import_service.LabelmeImportPlan:
    dataset_service.get_dataset_or_404(session, dataset_id)
    source = resolve_local_path(payload.path)
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"COCO JSON file does not exist: {source}")
    if source.suffix.lower() != ".json":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="COCO import source must be a .json file.")
    try:
        source_bytes = source.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read COCO JSON: {exc}") from exc
    source_hash = sha256(source_bytes).hexdigest()
    try:
        root = json.loads(source_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid COCO JSON: {exc}") from exc
    if not isinstance(root, dict):
        raise HTTPException(status_code=400, detail="COCO JSON root must be an object.")

    warnings: list[LabelmeImportIssue] = []
    errors: list[LabelmeImportIssue] = []
    images = root.get("images")
    categories = root.get("categories")
    raw_annotations = root.get("annotations")
    if not isinstance(images, list) or not isinstance(categories, list) or not isinstance(raw_annotations, list):
        errors.append(_issue("error", "INVALID_COCO_STRUCTURE", "COCO JSON requires images, categories and annotations arrays.", source))
        images = images if isinstance(images, list) else []
        categories = categories if isinstance(categories, list) else []
        raw_annotations = raw_annotations if isinstance(raw_annotations, list) else []

    category_names = _categories(categories, source, errors)
    grouped: dict[object, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    annotation_ids: Counter[object] = Counter()
    for index, item in enumerate(raw_annotations):
        if not isinstance(item, dict):
            errors.append(_issue("error", "INVALID_COCO_ANNOTATION", f"Annotation {index + 1} must be an object.", source))
            continue
        grouped[item.get("image_id")].append((index, item))
        if item.get("id") is not None:
            annotation_ids[item.get("id")] += 1
    for annotation_id, count in annotation_ids.items():
        if count > 1:
            warnings.append(_issue("warning", "DUPLICATE_ANNOTATION_ID", f"Annotation id {annotation_id!r} appears {count} times.", source))

    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id, Sample.file_type == "image")).all()
    matcher = annotation_import_service._SampleMatcher(samples)
    image_ids = Counter(item.get("id") for item in images if isinstance(item, dict))
    file_names = Counter(str(item.get("file_name") or "").replace("\\", "/").casefold() for item in images if isinstance(item, dict))
    operations: list[annotation_import_service.LabelmeImportOperation] = []
    seen_samples: set[int] = set()
    matched = 0
    skipped = 0
    for image_index, image in enumerate(images):
        if not isinstance(image, dict):
            errors.append(_issue("error", "INVALID_COCO_IMAGE", f"Image {image_index + 1} must be an object.", source))
            continue
        image_id = image.get("id")
        file_name = str(image.get("file_name") or "").strip()
        if image_id is None or not file_name:
            errors.append(_issue("error", "INVALID_COCO_IMAGE", f"Image {image_index + 1} requires id and file_name.", source))
            continue
        if image_ids[image_id] > 1:
            errors.append(_issue("error", "DUPLICATE_IMAGE_ID", f"COCO image id {image_id!r} is duplicated; matching is ambiguous.", source))
            continue
        normalized_name = file_name.replace("\\", "/").casefold()
        if file_names[normalized_name] > 1:
            errors.append(_issue("error", "DUPLICATE_IMAGE_FILE_NAME", f"COCO file_name {file_name!r} is duplicated.", source))
            continue
        sample, problem = matcher.match(image_path=file_name, fallback_stem=Path(file_name).stem)
        if sample is None:
            errors.append(_issue("error", problem, f"No unique dataset sample matched COCO file_name={file_name}.", source, sample_path=file_name))
            continue
        if sample.id is None:
            continue
        if sample.id in seen_samples:
            errors.append(_issue("error", "DUPLICATE_SAMPLE_MATCH", "Multiple COCO image entries matched the same dataset sample.", source, sample))
            continue
        seen_samples.add(sample.id)
        matched += 1
        actual_size = read_image_size(Path(sample.absolute_path))
        if actual_size is None:
            errors.append(_issue("error", "IMAGE_SIZE_UNAVAILABLE", "Image dimensions are required to validate COCO coordinates.", source, sample))
            continue
        annotations: list[AnnotationCreate] = []
        image_annotations = grouped.get(image_id, [])
        for annotation_index, raw in image_annotations:
            created, skipped_count = _parse_annotation(
                raw, annotation_index, source, sample, actual_size, category_names, warnings, errors, len(annotations)
            )
            annotations.extend(created)
            skipped += skipped_count
        if image_annotations and not annotations:
            errors.append(_issue("error", "NO_VALID_ANNOTATIONS", "COCO image has annotations, but none can be imported; existing annotations will not be cleared.", source, sample))
            continue
        operations.append(annotation_import_service.LabelmeImportOperation(
            sample_id=sample.id,
            sample_path=sample.relative_path,
            source_file=source,
            annotations=annotations,
        ))

    known_image_ids = {item.get("id") for item in images if isinstance(item, dict)}
    for missing_id in sorted((key for key in grouped if key not in known_image_ids), key=str):
        errors.append(_issue("error", "COCO_IMAGE_NOT_FOUND", f"Annotations reference missing image_id {missing_id!r}.", source))

    plan_hash = _plan_fingerprint(operations)
    if payload.expected_source_sha256 and payload.expected_source_sha256.lower() != source_hash:
        raise HTTPException(status_code=409, detail="COCO source changed after preview. Run preview again before importing.")
    if payload.expected_plan_fingerprint and payload.expected_plan_fingerprint.lower() != plan_hash:
        raise HTTPException(status_code=409, detail="COCO import targets changed after preview. Run preview again before importing.")
    return annotation_import_service.LabelmeImportPlan(
        dataset_id=dataset_id,
        source=source,
        source_size_bytes=len(source_bytes),
        source_sha256=source_hash,
        plan_fingerprint=plan_hash,
        checked_files=1,
        matched_files=matched,
        skipped_shapes=skipped,
        warnings=warnings[:100],
        errors=errors[:100],
        operations=operations,
        format="coco",
    )


def _categories(raw: list[Any], source: Path, errors: list[LabelmeImportIssue]) -> dict[object, str]:
    result: dict[object, str] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or item.get("id") is None or not str(item.get("name") or "").strip():
            errors.append(_issue("error", "INVALID_COCO_CATEGORY", f"Category {index + 1} requires id and name.", source))
            continue
        category_id = item["id"]
        if category_id in result:
            errors.append(_issue("error", "DUPLICATE_CATEGORY_ID", f"COCO category id {category_id!r} is duplicated.", source))
            continue
        result[category_id] = str(item["name"]).strip()
    return result


def _parse_annotation(
    raw: dict[str, Any], index: int, source: Path, sample: Sample, image_size: tuple[int, int],
    categories: dict[object, str], warnings: list[LabelmeImportIssue], errors: list[LabelmeImportIssue], z_order: int,
) -> tuple[list[AnnotationCreate], int]:
    category_id = raw.get("category_id")
    label = categories.get(category_id)
    if label is None:
        errors.append(_annotation_issue("COCO_CATEGORY_NOT_FOUND", f"category_id {category_id!r} is missing.", source, sample, index))
        return [], 1
    segmentation = raw.get("segmentation")
    if isinstance(segmentation, dict):
        warnings.append(_annotation_issue("UNSUPPORTED_RLE_MASK", "RLE mask is not supported; bbox is used when available.", source, sample, index, "warning"))
        segmentation = None
    if isinstance(segmentation, list) and segmentation:
        polygons = segmentation if all(isinstance(item, list) for item in segmentation) else [segmentation]
        created: list[AnnotationCreate] = []
        if len(polygons) > 1:
            warnings.append(_annotation_issue("MULTIPART_POLYGON_SPLIT", "Multipart segmentation is imported as separate polygons.", source, sample, index, "warning"))
        for polygon_index, polygon in enumerate(polygons):
            points = _number_list(polygon)
            if points is None or len(points) < 6 or len(points) % 2:
                errors.append(_annotation_issue("INVALID_COCO_POLYGON", "Polygon requires at least three coordinate pairs.", source, sample, index))
                continue
            annotation = AnnotationCreate(label=label, shape_type="polygon", points=points, group_id=_int_or_none(raw.get("id")), z_order=z_order + polygon_index, source="coco")
            if not _validate(annotation, image_size, source, sample, index, errors):
                continue
            created.append(annotation)
        return created, max(0, len(polygons) - len(created))
    bbox = _number_list(raw.get("bbox"))
    if bbox is None or len(bbox) != 4:
        errors.append(_annotation_issue("COCO_BBOX_REQUIRED", "Annotation requires bbox [x, y, width, height] or polygon segmentation.", source, sample, index))
        return [], 1
    x, y, width, height = bbox
    annotation = AnnotationCreate(label=label, shape_type="rectangle", points=[x, y, x + width, y + height], group_id=_int_or_none(raw.get("id")), z_order=z_order, source="coco")
    if not _validate(annotation, image_size, source, sample, index, errors):
        return [], 1
    return [annotation], 0


def _validate(annotation: AnnotationCreate, size: tuple[int, int], source: Path, sample: Sample, index: int, errors: list[LabelmeImportIssue]) -> bool:
    try:
        annotation_service.validate_annotation(annotation)
    except HTTPException as exc:
        errors.append(_annotation_issue("INVALID_SHAPE_GEOMETRY", str(exc.detail), source, sample, index))
        return False
    width, height = size
    if any(value < 0 for value in annotation.points) or any(
        value > (width if point_index % 2 == 0 else height)
        for point_index, value in enumerate(annotation.points)
    ):
        errors.append(_annotation_issue("COORDINATE_OUT_OF_BOUNDS", f"Coordinates exceed image bounds {width}x{height}.", source, sample, index))
        return False
    return True


def _plan_fingerprint(operations: list[annotation_import_service.LabelmeImportOperation]) -> str:
    payload = [{"sample_id": operation.sample_id, "annotations": [item.model_dump(mode="json") for item in operation.annotations]} for operation in operations]
    return sha256(json.dumps({"format": "coco", "operations": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _number_list(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _annotation_issue(code: str, message: str, source: Path, sample: Sample, index: int, severity: str = "error") -> LabelmeImportIssue:
    return _issue(severity, code, f"Annotation {index + 1}: {message}", source, sample)


def _issue(severity: str, code: str, message: str, source: Path, sample: Sample | None = None, *, sample_path: str | None = None) -> LabelmeImportIssue:
    return LabelmeImportIssue(severity=severity, code=code, message=message, file_path=str(source), sample_id=sample.id if sample else None, sample_path=sample.relative_path if sample else sample_path)
