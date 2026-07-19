import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.annotation import AnnotationCreate, AnnotationReplaceRequest
from app.schemas.annotation_import import LabelmeImportIssue, LabelmeImportRequest, LabelmeImportResult
from app.services import annotation_service, dataset_service
from app.utils.image_size import read_image_size
from app.utils.paths import resolve_local_path

SUPPORTED_LABELME_SHAPES = {"rectangle", "polygon", "point", "points"}


def import_labelme_annotations(
    session: Session,
    dataset_id: int,
    payload: LabelmeImportRequest,
) -> LabelmeImportResult:
    dataset_service.get_dataset_or_404(session, dataset_id)
    source = resolve_local_path(payload.path)
    source_files = _resolve_labelme_sources(source, payload.mode)
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
    matcher = _SampleMatcher(samples)
    warnings: list[LabelmeImportIssue] = []
    errors: list[LabelmeImportIssue] = []
    operations: list[tuple[Sample, list[AnnotationCreate], Path]] = []
    matched_files = 0
    created_annotations = 0
    skipped_shapes = 0
    seen_sample_ids: set[int] = set()

    if not samples:
        errors.append(
            _issue("error", "NO_SAMPLES", "Dataset has no registered samples. Run scan before importing labelme annotations.")
        )

    for source_file in source_files:
        parsed = _load_labelme_json(source_file, errors)
        if parsed is None:
            continue
        sample = _match_import_sample(session, dataset_id, payload, parsed, source_file, matcher, errors)
        if sample is None:
            continue
        sample_id = sample.id or 0
        if sample_id in seen_sample_ids:
            warnings.append(
                _issue(
                    "warning",
                    "DUPLICATE_SAMPLE_IMPORT_SKIPPED",
                    "Multiple labelme files matched the same sample; only the first file is used.",
                    file_path=str(source_file),
                    sample_id=sample_id,
                    sample_path=sample.relative_path,
                )
            )
            continue
        seen_sample_ids.add(sample_id)
        matched_files += 1

        annotations, skipped, raw_shape_count = _annotations_from_labelme_shapes(parsed, source_file, sample, warnings, errors)
        skipped_shapes += skipped
        if raw_shape_count > 0 and not annotations and skipped > 0:
            errors.append(
                _issue(
                    "error",
                    "NO_VALID_SHAPES",
                    "Labelme file contains shapes, but none can be imported.",
                    file_path=str(source_file),
                    sample_id=sample.id,
                    sample_path=sample.relative_path,
                )
            )
            continue
        _warn_on_image_size_mismatch(parsed, source_file, sample, warnings)
        operations.append((sample, annotations, source_file))
        created_annotations += len(annotations)

    if not payload.dry_run:
        for sample, annotations, _source_file in operations:
            next_annotations = annotations
            if payload.strategy == "append":
                existing_annotations = [
                    _annotation_read_to_create(item)
                    for item in annotation_service.list_sample_annotations(session, sample.id or 0)
                ]
                appended_annotations = [
                    item.model_copy(update={"z_order": len(existing_annotations) + index})
                    for index, item in enumerate(annotations)
                ]
                next_annotations = [
                    *existing_annotations,
                    *appended_annotations,
                ]
            annotation_service.replace_sample_annotations(
                session,
                sample.id or 0,
                AnnotationReplaceRequest(
                    annotations=next_annotations,
                    sync_sample_tags=payload.sync_sample_tags,
                ),
            )

    return LabelmeImportResult(
        dataset_id=dataset_id,
        source_path=str(source),
        mode=payload.mode,
        strategy=payload.strategy,
        dry_run=payload.dry_run,
        checked_files=len(source_files),
        matched_files=matched_files,
        imported_samples=len(operations),
        created_annotations=created_annotations,
        skipped_shapes=skipped_shapes,
        warnings=warnings[:100],
        errors=errors[:100],
    )


def _resolve_labelme_sources(source: Path, mode: str) -> list[Path]:
    if mode == "file":
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Labelme JSON file does not exist: {source}")
        if source.suffix.lower() != ".json":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Labelme import file must be a .json file.")
        return [source]

    if not source.exists() or not source.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Labelme JSON directory does not exist: {source}")
    return sorted(path for path in source.rglob("*.json") if path.is_file())


def _load_labelme_json(source_file: Path, errors: list[LabelmeImportIssue]) -> dict[str, Any] | None:
    try:
        with source_file.open("r", encoding="utf-8-sig") as file:
            parsed = json.load(file)
    except json.JSONDecodeError as exc:
        errors.append(_issue("error", "INVALID_JSON", f"Invalid labelme JSON: {exc.msg}", file_path=str(source_file)))
        return None
    except OSError as exc:
        errors.append(_issue("error", "READ_FAILED", f"Unable to read labelme JSON: {exc}", file_path=str(source_file)))
        return None
    if not isinstance(parsed, dict):
        errors.append(_issue("error", "INVALID_LABELME_ROOT", "Labelme JSON root must be an object.", file_path=str(source_file)))
        return None
    return parsed


def _match_import_sample(
    session: Session,
    dataset_id: int,
    payload: LabelmeImportRequest,
    parsed: dict[str, Any],
    source_file: Path,
    matcher: "_SampleMatcher",
    errors: list[LabelmeImportIssue],
) -> Sample | None:
    if payload.sample_id is not None:
        sample = session.get(Sample, payload.sample_id)
        if not sample or sample.dataset_id != dataset_id:
            errors.append(
                _issue(
                    "error",
                    "SAMPLE_NOT_FOUND",
                    f"Sample {payload.sample_id} was not found in this dataset.",
                    file_path=str(source_file),
                )
            )
            return None
        if sample.file_type != "image":
            errors.append(
                _issue(
                    "error",
                    "SAMPLE_NOT_IMAGE",
                    "Labelme annotations can only be imported into image samples.",
                    file_path=str(source_file),
                    sample_id=sample.id,
                    sample_path=sample.relative_path,
                )
            )
            return None
        return sample

    image_path = str(parsed.get("imagePath") or "").strip()
    sample, problem = matcher.match(image_path=image_path, fallback_stem=source_file.stem)
    if sample:
        return sample
    errors.append(_issue("error", problem, f"No sample matched labelme imagePath={image_path or source_file.stem}.", file_path=str(source_file)))
    return None


def _annotations_from_labelme_shapes(
    parsed: dict[str, Any],
    source_file: Path,
    sample: Sample,
    warnings: list[LabelmeImportIssue],
    errors: list[LabelmeImportIssue],
) -> tuple[list[AnnotationCreate], int, int]:
    raw_shapes = parsed.get("shapes", [])
    if not isinstance(raw_shapes, list):
        errors.append(
            _issue(
                "error",
                "INVALID_SHAPES",
                "Labelme JSON must contain a shapes array.",
                file_path=str(source_file),
                sample_id=sample.id,
                sample_path=sample.relative_path,
            )
        )
        return [], 0, 0

    annotations: list[AnnotationCreate] = []
    skipped = 0
    for index, raw_shape in enumerate(raw_shapes):
        annotation = _annotation_from_labelme_shape(raw_shape, index, source_file, sample, warnings, errors)
        if annotation is None:
            skipped += 1
            continue
        annotations.append(annotation)
    return annotations, skipped, len(raw_shapes)


def _annotation_from_labelme_shape(
    raw_shape: Any,
    index: int,
    source_file: Path,
    sample: Sample,
    warnings: list[LabelmeImportIssue],
    errors: list[LabelmeImportIssue],
) -> AnnotationCreate | None:
    if not isinstance(raw_shape, dict):
        errors.append(_shape_issue("error", "INVALID_SHAPE", "Labelme shape must be an object.", source_file, sample, index))
        return None
    shape_type = str(raw_shape.get("shape_type") or "polygon").strip() or "polygon"
    if shape_type not in SUPPORTED_LABELME_SHAPES:
        warnings.append(
            _shape_issue(
                "warning",
                "UNSUPPORTED_SHAPE_SKIPPED",
                f"Unsupported labelme shape_type skipped: {shape_type}",
                source_file,
                sample,
                index,
            )
        )
        return None
    label = str(raw_shape.get("label") or "").strip()
    if not label:
        errors.append(_shape_issue("error", "SHAPE_LABEL_REQUIRED", "Labelme shape label is required.", source_file, sample, index))
        return None
    points = _flatten_labelme_points(raw_shape.get("points"), shape_type)
    if points is None:
        errors.append(_shape_issue("error", "INVALID_SHAPE_POINTS", f"Invalid points for labelme {shape_type} shape.", source_file, sample, index))
        return None

    annotation = AnnotationCreate(
        label=label,
        tag_id=None,
        shape_type=shape_type,
        points=points,
        flags=_bool_dict(raw_shape.get("flags")),
        attributes=_dict_or_empty(raw_shape.get("attributes")),
        group_id=_int_or_none(raw_shape.get("group_id")),
        z_order=index,
        locked=False,
        hidden=False,
        source="labelme",
        notes=str(raw_shape.get("description") or "").strip() or None,
    )
    try:
        annotation_service.validate_annotation(annotation)
    except HTTPException as exc:
        errors.append(_shape_issue("error", "INVALID_SHAPE_GEOMETRY", str(exc.detail), source_file, sample, index))
        return None
    return annotation


def _flatten_labelme_points(value: Any, shape_type: str) -> list[float] | None:
    if not isinstance(value, list):
        return None
    paired: list[tuple[float, float]] = []
    for item in value:
        if not isinstance(item, list | tuple) or len(item) < 2:
            return None
        try:
            x = float(item[0])
            y = float(item[1])
        except (TypeError, ValueError):
            return None
        paired.append((x, y))

    if shape_type == "rectangle":
        if len(paired) < 2:
            return None
        x1, y1 = paired[0]
        x2, y2 = paired[1]
        return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
    if shape_type == "point":
        if len(paired) != 1:
            return None
        return [paired[0][0], paired[0][1]]
    if shape_type == "polygon" and len(paired) < 3:
        return None
    if shape_type == "points" and not paired:
        return None

    flattened: list[float] = []
    for x, y in paired:
        flattened.extend([x, y])
    return flattened


def _warn_on_image_size_mismatch(
    parsed: dict[str, Any],
    source_file: Path,
    sample: Sample,
    warnings: list[LabelmeImportIssue],
) -> None:
    expected_width = parsed.get("imageWidth")
    expected_height = parsed.get("imageHeight")
    if expected_width is None or expected_height is None:
        return
    actual_size = read_image_size(Path(sample.absolute_path))
    if actual_size is None:
        warnings.append(
            _issue(
                "warning",
                "IMAGE_SIZE_UNAVAILABLE",
                "Sample image size could not be read for labelme dimension comparison.",
                file_path=str(source_file),
                sample_id=sample.id,
                sample_path=sample.relative_path,
            )
        )
        return
    actual_width, actual_height = actual_size
    try:
        labelme_width = int(expected_width)
        labelme_height = int(expected_height)
    except (TypeError, ValueError):
        return
    if (labelme_width, labelme_height) != (actual_width, actual_height):
        warnings.append(
            _issue(
                "warning",
                "IMAGE_SIZE_MISMATCH",
                f"Labelme image size {labelme_width}x{labelme_height} differs from sample image size {actual_width}x{actual_height}.",
                file_path=str(source_file),
                sample_id=sample.id,
                sample_path=sample.relative_path,
            )
        )


def _annotation_read_to_create(annotation) -> AnnotationCreate:
    return AnnotationCreate(
        label=annotation.label,
        tag_id=annotation.tag_id,
        shape_type=annotation.shape_type,
        points=annotation.points,
        flags=annotation.flags,
        attributes=annotation.attributes,
        group_id=annotation.group_id,
        z_order=annotation.z_order,
        locked=annotation.locked,
        hidden=annotation.hidden,
        source=annotation.source,
        notes=annotation.notes,
    )


def _bool_dict(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {str(key): bool(item) for key, item in value.items()}


def _dict_or_empty(value: Any) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _shape_issue(
    severity: str,
    code: str,
    message: str,
    source_file: Path,
    sample: Sample,
    index: int,
) -> LabelmeImportIssue:
    return _issue(
        severity,
        code,
        f"Shape {index + 1}: {message}",
        file_path=str(source_file),
        sample_id=sample.id,
        sample_path=sample.relative_path,
    )


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    file_path: str | None = None,
    sample_id: int | None = None,
    sample_path: str | None = None,
) -> LabelmeImportIssue:
    return LabelmeImportIssue(
        severity=severity,
        code=code,
        message=message,
        file_path=file_path,
        sample_id=sample_id,
        sample_path=sample_path,
    )


def _normalize_relative_key(value: str) -> str:
    return value.strip().replace("\\", "/").removeprefix("./").casefold()


class _SampleMatcher:
    def __init__(self, samples: list[Sample]) -> None:
        self.relative_index: dict[str, Sample] = {}
        self.filename_index: dict[str, list[Sample]] = {}
        self.stem_index: dict[str, list[Sample]] = {}
        for sample in samples:
            if sample.file_type != "image":
                continue
            self.relative_index.setdefault(_normalize_relative_key(sample.relative_path), sample)
            self.filename_index.setdefault(sample.filename.casefold(), []).append(sample)
            self.stem_index.setdefault(Path(sample.filename).stem.casefold(), []).append(sample)

    def match(self, *, image_path: str, fallback_stem: str) -> tuple[Sample | None, str]:
        if image_path:
            relative_key = _normalize_relative_key(image_path)
            sample = self.relative_index.get(relative_key)
            if sample:
                return sample, ""
            filename = Path(image_path.replace("\\", "/")).name.casefold()
            sample, problem = self._unique_from_index(self.filename_index, filename)
            if sample or problem:
                return sample, problem
        return self._unique_from_index(self.stem_index, fallback_stem.casefold())

    def _unique_from_index(self, index: dict[str, list[Sample]], key: str) -> tuple[Sample | None, str]:
        matches = index.get(key, [])
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, "AMBIGUOUS_SAMPLE_MATCH"
        return None, "SAMPLE_MATCH_NOT_FOUND"
