from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.annotation import AnnotationCreate
from app.schemas.annotation_import import AnnotationImportRequest, LabelmeImportIssue
from app.services import annotation_import_service, annotation_service, dataset_service
from app.utils.image_size import read_image_size
from app.utils.paths import resolve_local_path


def prepare_yolo_import(
    session: Session,
    dataset_id: int,
    payload: AnnotationImportRequest,
) -> annotation_import_service.LabelmeImportPlan:
    dataset_service.get_dataset_or_404(session, dataset_id)
    source = resolve_local_path(payload.path)
    if not source.exists() or not source.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"YOLO directory does not exist: {source}")

    warnings: list[LabelmeImportIssue] = []
    errors: list[LabelmeImportIssue] = []
    classes_file = source / "classes.txt"
    yaml_file = source / "data.yaml"
    class_names = _read_class_names(yaml_file, classes_file, errors)
    label_root = source / "labels" if (source / "labels").is_dir() else source
    label_files = sorted(
        path for path in label_root.rglob("*.txt")
        if path.is_file() and path.resolve() != classes_file.resolve()
    )
    fingerprint_files = [path for path in (yaml_file, classes_file) if path.is_file()]
    fingerprint_files.extend(label_files)
    source_size, source_digest = _source_fingerprint(source, fingerprint_files, errors)

    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id, Sample.file_type == "image")).all()
    matcher = _YoloSampleMatcher(samples)
    operations: list[annotation_import_service.LabelmeImportOperation] = []
    seen_samples: set[int] = set()
    skipped = 0
    matched = 0
    for label_file in label_files:
        sample, problem = matcher.match(label_file.relative_to(label_root))
        if sample is None:
            errors.append(_issue("error", problem, "No unique dataset image matched this YOLO label file.", label_file))
            continue
        if sample.id is None:
            continue
        if sample.id in seen_samples:
            warnings.append(_issue("warning", "DUPLICATE_SAMPLE_IMPORT_SKIPPED", "Multiple YOLO files matched this sample; only the first is used.", label_file, sample))
            continue
        seen_samples.add(sample.id)
        matched += 1
        size = read_image_size(Path(sample.absolute_path))
        if size is None:
            errors.append(_issue("error", "IMAGE_SIZE_UNAVAILABLE", "Image dimensions are required to convert normalized YOLO coordinates.", label_file, sample))
            continue
        annotations, skipped_count, raw_count = _parse_label_file(
            label_file,
            sample,
            size,
            class_names,
            payload.format,
            warnings,
            errors,
        )
        skipped += skipped_count
        if raw_count > 0 and not annotations:
            errors.append(_issue("error", "NO_VALID_ANNOTATIONS", "YOLO label file contains rows, but none can be imported; existing annotations will not be cleared.", label_file, sample))
            continue
        operations.append(annotation_import_service.LabelmeImportOperation(
            sample_id=sample.id,
            sample_path=sample.relative_path,
            source_file=label_file,
            annotations=annotations,
        ))

    if not label_files:
        errors.append(_issue("error", "NO_LABEL_FILES", "No YOLO .txt label files were found under labels/ or the selected directory.", source))
    plan_fingerprint = _plan_fingerprint(payload.format, source, operations)
    _check_expected_fingerprints(payload, source_digest, plan_fingerprint)
    return annotation_import_service.LabelmeImportPlan(
        dataset_id=dataset_id,
        source=source,
        source_size_bytes=source_size,
        source_sha256=source_digest,
        plan_fingerprint=plan_fingerprint,
        checked_files=len(label_files),
        matched_files=matched,
        skipped_shapes=skipped,
        warnings=warnings[:100],
        errors=errors[:100],
        operations=operations,
        format=payload.format,
    )


def _read_class_names(yaml_file: Path, classes_file: Path, errors: list[LabelmeImportIssue]) -> list[str]:
    if yaml_file.is_file():
        try:
            lines = yaml_file.read_text(encoding="utf-8-sig").splitlines()
            names = _names_from_yaml_lines(lines)
            if names:
                return names
        except OSError as exc:
            errors.append(_issue("error", "READ_FAILED", f"Unable to read data.yaml: {exc}", yaml_file))
    if classes_file.is_file():
        try:
            names = [line.strip() for line in classes_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if names:
                return names
        except OSError as exc:
            errors.append(_issue("error", "READ_FAILED", f"Unable to read classes.txt: {exc}", classes_file))
    errors.append(_issue("error", "YOLO_CLASSES_REQUIRED", "YOLO import requires category names in data.yaml or classes.txt.", yaml_file))
    return []


def _names_from_yaml_lines(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("names:"):
            continue
        inline = stripped.partition(":")[2].strip()
        if inline:
            try:
                parsed = ast.literal_eval(inline)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            if isinstance(parsed, dict):
                return [str(parsed[key]).strip() for key in sorted(parsed, key=lambda item: int(item)) if str(parsed[key]).strip()]
            if inline.startswith("[") and inline.endswith("]"):
                return [item.strip().strip("'\"") for item in inline[1:-1].split(",") if item.strip().strip("'\"")]
            if inline.startswith("{") and inline.endswith("}"):
                mapped: dict[int, str] = {}
                for item in inline[1:-1].split(","):
                    key, separator, value = item.partition(":")
                    if separator and key.strip().isdigit() and value.strip():
                        mapped[int(key.strip())] = value.strip().strip("'\"")
                if mapped:
                    return [mapped[key] for key in sorted(mapped)]
        mapped: dict[int, str] = {}
        for child in lines[index + 1:]:
            if child and not child[0].isspace():
                break
            key, separator, value = child.strip().partition(":")
            if separator and key.isdigit() and value.strip():
                mapped[int(key)] = value.strip().strip("'\"")
        return [mapped[key] for key in sorted(mapped)]
    return []


def _parse_label_file(
    path: Path,
    sample: Sample,
    size: tuple[int, int],
    class_names: list[str],
    import_format: str,
    warnings: list[LabelmeImportIssue],
    errors: list[LabelmeImportIssue],
) -> tuple[list[AnnotationCreate], int, int]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        errors.append(_issue("error", "READ_FAILED", f"Unable to read YOLO label file: {exc}", path, sample))
        return [], 1, 0
    annotations: list[AnnotationCreate] = []
    skipped = 0
    width, height = size
    raw_count = 0
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        raw_count += 1
        try:
            values = [float(item) for item in line.split()]
        except ValueError:
            values = []
        if len(values) < 5 or not values[0].is_integer():
            errors.append(_line_issue("INVALID_YOLO_ROW", "Expected a numeric class id followed by normalized coordinates.", path, sample, line_number))
            skipped += 1
            continue
        class_id = int(values[0])
        if class_id < 0 or class_id >= len(class_names):
            errors.append(_line_issue("YOLO_CLASS_NOT_FOUND", f"Class id {class_id} is missing from data.yaml/classes.txt.", path, sample, line_number))
            skipped += 1
            continue
        coords = values[1:]
        if any(value < 0 or value > 1 for value in coords):
            errors.append(_line_issue("COORDINATE_OUT_OF_BOUNDS", "YOLO normalized coordinates must stay within 0..1.", path, sample, line_number))
            skipped += 1
            continue
        if import_format == "yolo_detection" and len(coords) == 4:
            cx, cy, box_width, box_height = coords
            points = [(cx - box_width / 2) * width, (cy - box_height / 2) * height,
                      (cx + box_width / 2) * width, (cy + box_height / 2) * height]
            shape_type = "rectangle"
        elif import_format == "yolo_segmentation" and len(coords) >= 6 and len(coords) % 2 == 0:
            points = [value * (width if index % 2 == 0 else height) for index, value in enumerate(coords)]
            shape_type = "polygon"
        else:
            errors.append(_line_issue(
                "UNSUPPORTED_YOLO_FORMAT",
                "This row does not match the selected detection/segmentation format; pose and OBB are not supported.",
                path, sample, line_number,
            ))
            skipped += 1
            continue
        if any(value < 0 for value in points) or any(
            value > (width if point_index % 2 == 0 else height)
            for point_index, value in enumerate(points)
        ):
            errors.append(_line_issue("COORDINATE_OUT_OF_BOUNDS", f"Converted coordinates exceed image bounds {width}x{height}.", path, sample, line_number))
            skipped += 1
            continue
        annotation = AnnotationCreate(
            label=class_names[class_id],
            shape_type=shape_type,
            points=points,
            z_order=len(annotations),
            source=import_format,
        )
        try:
            annotation_service.validate_annotation(annotation)
        except HTTPException as exc:
            errors.append(_line_issue("INVALID_SHAPE_GEOMETRY", str(exc.detail), path, sample, line_number))
            skipped += 1
            continue
        annotations.append(annotation)
    return annotations, skipped, raw_count


class _YoloSampleMatcher:
    def __init__(self, samples: list[Sample]) -> None:
        self.by_stem: dict[str, list[Sample]] = {}
        self.by_relative_stem: dict[str, list[Sample]] = {}
        for sample in samples:
            normalized = Path(sample.relative_path.replace("\\", "/"))
            stem_key = normalized.stem.casefold()
            relative_stem = normalized.with_suffix("").as_posix().casefold()
            self.by_stem.setdefault(stem_key, []).append(sample)
            self.by_relative_stem.setdefault(relative_stem, []).append(sample)

    def match(self, label_relative: Path) -> tuple[Sample | None, str]:
        label_stem = label_relative.with_suffix("").as_posix().casefold()
        candidates = [label_stem]
        parts = label_stem.split("/")
        for index in range(len(parts)):
            candidates.append("/".join(parts[index:]))
            candidates.append("images/" + "/".join(parts[index:]))
        exact: dict[int, Sample] = {}
        for key in candidates:
            for sample in self.by_relative_stem.get(key, []):
                if sample.id is not None:
                    exact[sample.id] = sample
        if len(exact) == 1:
            return next(iter(exact.values())), ""
        if len(exact) > 1:
            return None, "AMBIGUOUS_SAMPLE_MATCH"
        fallback = self.by_stem.get(label_relative.stem.casefold(), [])
        if len(fallback) == 1:
            return fallback[0], ""
        return None, "AMBIGUOUS_SAMPLE_MATCH" if fallback else "SAMPLE_MATCH_NOT_FOUND"


def _source_fingerprint(root: Path, files: list[Path], errors: list[LabelmeImportIssue]) -> tuple[int, str]:
    hasher = sha256()
    total = 0
    for path in sorted(set(files)):
        try:
            content = path.read_bytes()
        except OSError as exc:
            errors.append(_issue("error", "READ_FAILED", f"Unable to read source file: {exc}", path))
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        hasher.update(len(relative).to_bytes(8, "big")); hasher.update(relative)
        hasher.update(len(content).to_bytes(8, "big")); hasher.update(content)
        total += len(content)
    return total, hasher.hexdigest()


def _plan_fingerprint(import_format: str, root: Path, operations: list[annotation_import_service.LabelmeImportOperation]) -> str:
    payload = [{
        "sample_id": item.sample_id,
        "source": item.source_file.relative_to(root).as_posix(),
        "annotations": [annotation.model_dump(mode="json") for annotation in item.annotations],
    } for item in operations]
    return sha256(json.dumps({"format": import_format, "operations": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _check_expected_fingerprints(payload: AnnotationImportRequest, source_hash: str, plan_hash: str) -> None:
    if payload.expected_source_sha256 and payload.expected_source_sha256.lower() != source_hash:
        raise HTTPException(status_code=409, detail="YOLO source changed after preview. Run preview again before importing.")
    if payload.expected_plan_fingerprint and payload.expected_plan_fingerprint.lower() != plan_hash:
        raise HTTPException(status_code=409, detail="YOLO import targets changed after preview. Run preview again before importing.")


def _line_issue(code: str, message: str, path: Path, sample: Sample, line: int) -> LabelmeImportIssue:
    return _issue("error", code, f"Line {line}: {message}", path, sample)


def _issue(severity: str, code: str, message: str, path: Path, sample: Sample | None = None) -> LabelmeImportIssue:
    return LabelmeImportIssue(
        severity=severity,
        code=code,
        message=message,
        file_path=str(path),
        sample_id=sample.id if sample else None,
        sample_path=sample.relative_path if sample else None,
    )
