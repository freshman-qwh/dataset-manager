from dataclasses import dataclass
from hashlib import sha256
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


@dataclass(frozen=True)
class LabelmeImportOperation:
    sample_id: int
    sample_path: str
    source_file: Path
    annotations: list[AnnotationCreate]


@dataclass(frozen=True)
class LabelmeImportPlan:
    dataset_id: int
    source: Path
    source_size_bytes: int
    source_sha256: str
    plan_fingerprint: str
    checked_files: int
    matched_files: int
    skipped_shapes: int
    warnings: list[LabelmeImportIssue]
    errors: list[LabelmeImportIssue]
    operations: list[LabelmeImportOperation]


def import_labelme_annotations(
    session: Session,
    dataset_id: int,
    payload: LabelmeImportRequest,
) -> LabelmeImportResult:
    plan = prepare_labelme_import(session, dataset_id, payload)
    if not payload.dry_run:
        for operation in plan.operations:
            next_annotations = operation.annotations
            if payload.strategy == "append":
                existing_annotations = [
                    _annotation_read_to_create(item)
                    for item in annotation_service.list_sample_annotations(session, operation.sample_id)
                ]
                next_annotations = append_annotations(existing_annotations, operation.annotations)
            annotation_service.replace_sample_annotations(
                session,
                operation.sample_id,
                AnnotationReplaceRequest(annotations=next_annotations, save_mode="draft"),
            )
            if payload.sync_sample_tags:
                annotation_service.sync_annotation_classes_to_sample_tags(session, operation.sample_id)
    return labelme_import_result(plan, payload)


def prepare_labelme_import(
    session: Session,
    dataset_id: int,
    payload: LabelmeImportRequest,
) -> LabelmeImportPlan:
    dataset_service.get_dataset_or_404(session, dataset_id)
    source = resolve_local_path(payload.path)
    source_files = _resolve_labelme_sources(source, payload.mode)
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
    matcher = _SampleMatcher(samples)
    warnings: list[LabelmeImportIssue] = []
    errors: list[LabelmeImportIssue] = []
    operations: list[LabelmeImportOperation] = []
    matched_files = 0
    skipped_shapes = 0
    seen_sample_ids: set[int] = set()

    if not samples:
        errors.append(
            _issue("error", "NO_SAMPLES", "Dataset has no registered samples. Run scan before importing labelme annotations.")
        )

    source_hasher = sha256()
    source_size_bytes = 0
    for source_file in source_files:
        source_bytes = _read_labelme_bytes(source_file, errors)
        if source_bytes is None:
            continue
        relative_source = source_file.name if payload.mode == "file" else source_file.relative_to(source).as_posix()
        relative_bytes = relative_source.encode("utf-8")
        source_hasher.update(len(relative_bytes).to_bytes(8, "big"))
        source_hasher.update(relative_bytes)
        source_hasher.update(len(source_bytes).to_bytes(8, "big"))
        source_hasher.update(source_bytes)
        source_size_bytes += len(source_bytes)
        parsed = _load_labelme_json(source_file, source_bytes, errors)
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
        if sample.id is None:
            raise RuntimeError("A persisted LabelMe import sample must have an id.")
        operations.append(
            LabelmeImportOperation(
                sample_id=sample.id,
                sample_path=sample.relative_path,
                source_file=source_file,
                annotations=annotations,
            )
        )

    source_sha256 = source_hasher.hexdigest()
    if payload.expected_source_sha256 is not None and source_sha256 != payload.expected_source_sha256.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LabelMe source changed after preview. Run preview again before importing.",
        )
    plan_payload = [
        {
            "sample_id": operation.sample_id,
            "source": operation.source_file.name if payload.mode == "file" else operation.source_file.relative_to(source).as_posix(),
            "annotations": [item.model_dump(mode="json") for item in operation.annotations],
        }
        for operation in operations
    ]
    plan_fingerprint = sha256(
        json.dumps(plan_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if payload.expected_plan_fingerprint is not None and plan_fingerprint != payload.expected_plan_fingerprint.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LabelMe import targets changed after preview. Run preview again before importing.",
        )
    return LabelmeImportPlan(
        dataset_id=dataset_id,
        source=source,
        source_size_bytes=source_size_bytes,
        source_sha256=source_sha256,
        plan_fingerprint=plan_fingerprint,
        checked_files=len(source_files),
        matched_files=matched_files,
        skipped_shapes=skipped_shapes,
        warnings=warnings[:100],
        errors=errors[:100],
        operations=operations,
    )


def labelme_import_result(plan: LabelmeImportPlan, payload: LabelmeImportRequest) -> LabelmeImportResult:
    return LabelmeImportResult(
        dataset_id=plan.dataset_id,
        source_path=str(plan.source),
        mode=payload.mode,
        strategy=payload.strategy,
        dry_run=payload.dry_run,
        source_size_bytes=plan.source_size_bytes,
        source_sha256=plan.source_sha256,
        plan_fingerprint=plan.plan_fingerprint,
        checked_files=plan.checked_files,
        matched_files=plan.matched_files,
        imported_samples=len(plan.operations),
        created_annotations=sum(len(operation.annotations) for operation in plan.operations),
        skipped_shapes=plan.skipped_shapes,
        warnings=plan.warnings,
        errors=plan.errors,
    )


def append_annotations(
    existing_annotations: list[AnnotationCreate],
    imported_annotations: list[AnnotationCreate],
) -> list[AnnotationCreate]:
    appended_annotations = [
        item.model_copy(update={"z_order": len(existing_annotations) + index})
        for index, item in enumerate(imported_annotations)
    ]
    return [*existing_annotations, *appended_annotations]


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


def _read_labelme_bytes(source_file: Path, errors: list[LabelmeImportIssue]) -> bytes | None:
    try:
        return source_file.read_bytes()
    except OSError as exc:
        errors.append(_issue("error", "READ_FAILED", f"Unable to read labelme JSON: {exc}", file_path=str(source_file)))
        return None


def _load_labelme_json(
    source_file: Path,
    source_bytes: bytes,
    errors: list[LabelmeImportIssue],
) -> dict[str, Any] | None:
    try:
        parsed = json.loads(source_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        message = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
        errors.append(_issue("error", "INVALID_JSON", f"Invalid labelme JSON: {message}", file_path=str(source_file)))
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

    flags = _bool_dict(raw_shape.get("flags"))
    attributes = _dict_or_empty(raw_shape.get("attributes"))
    for key in ("occluded", "truncated", "difficult"):
        if key in flags and key not in attributes:
            attributes[key] = flags[key]

    annotation = AnnotationCreate(
        label=label,
        class_id=None,
        shape_type=shape_type,
        points=points,
        flags=flags,
        attributes=attributes,
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
        class_id=annotation.class_id,
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
