from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from sqlmodel import Session

from app.models.sample import Sample
from app.schemas.annotation import AnnotationRead
from app.schemas.annotation_export import (
    AnnotationClassMapItem,
    AnnotationExportIssue,
    AnnotationExportPrecheckRequest,
    AnnotationExportPrecheckResponse,
)
from app.services import annotation_service, dataset_service, sample_service
from app.services.annotation_geometry import (
    pair_points,
    points_within_image,
    polygon_area,
    polygon_to_bbox,
    rectangle_to_bbox,
)
from app.utils.image_size import read_image_size

ISSUE_LIMIT = 200

LABELME_FORMATS = {"labelme"}
DETECTION_FORMATS = {"coco_detection", "yolo_detection", "voc"}
SEGMENTATION_FORMATS = {"coco_segmentation", "yolo_segmentation"}


class _IssueCollector:
    def __init__(self, limit: int = ISSUE_LIMIT) -> None:
        self.limit = limit
        self._issues = {"error": [], "warning": [], "info": []}
        self.counts = {"error": 0, "warning": 0, "info": 0}

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        *,
        sample_id: int | None = None,
        sample_path: str | None = None,
        annotation_id: int | None = None,
    ) -> None:
        self.counts[severity] += 1
        issue = AnnotationExportIssue(
            severity=severity,
            code=code,
            message=message,
            sample_id=sample_id,
            sample_path=sample_path,
            annotation_id=annotation_id,
        )
        if len(self._issues[severity]) < self.limit:
            self._issues[severity].append(issue)

    def visible_issues(self) -> list[AnnotationExportIssue]:
        issues: list[AnnotationExportIssue] = []
        for severity in ("error", "warning", "info"):
            remaining = self.limit - len(issues)
            if remaining <= 0:
                break
            issues.extend(self._issues[severity][:remaining])
        return issues

    def truncated_count(self) -> int:
        return sum(self.counts.values()) - len(self.visible_issues())


def precheck_annotation_export(
    session: Session,
    dataset_id: int,
    payload: AnnotationExportPrecheckRequest,
) -> AnnotationExportPrecheckResponse:
    dataset_service.get_dataset_or_404(session, dataset_id)
    issues = _IssueCollector()
    samples = _filtered_image_samples(session, dataset_id, payload, issues)
    sample_ids = [sample.id for sample in samples if sample.id is not None]
    annotations_by_sample = annotation_service.annotations_by_sample(session, sample_ids)
    _check_split_leakage(samples, issues)

    labels: set[str] = set()
    annotated_sample_count = 0
    exportable_object_count = 0
    skipped_object_count = 0

    if not samples:
        issues.add("error", "NO_IMAGE_SAMPLES", "No image samples match the export query.")

    for sample in samples:
        sample_id = sample.id or 0
        annotations = annotations_by_sample.get(sample_id, [])
        if annotations:
            annotated_sample_count += 1
        elif not payload.include_empty:
            issues.add(
                "info",
                "EMPTY_SAMPLE_SKIPPED",
                "Sample has no annotations and will be skipped.",
                sample_id=sample_id,
                sample_path=sample.relative_path,
            )
            continue

        image_size = read_image_size(Path(sample.absolute_path))
        if image_size is None:
            issues.add(
                "error",
                "IMAGE_SIZE_UNAVAILABLE",
                "Image width and height could not be read.",
                sample_id=sample_id,
                sample_path=sample.relative_path,
            )
            skipped_object_count += len(annotations)
            continue
        image_width, image_height = image_size

        for annotation in annotations:
            outcome = _check_annotation(
                payload.format,
                annotation,
                image_width,
                image_height,
                sample_id=sample_id,
                sample_path=sample.relative_path,
                issues=issues,
            )
            if outcome == "exportable":
                labels.add(annotation.label.strip())
                exportable_object_count += 1
            else:
                skipped_object_count += 1

    class_map = _build_class_map(labels)
    if not class_map and annotations_by_sample:
        issues.add("error", "EMPTY_CLASS_MAP", "No annotation labels are available for class mapping.")
    if exportable_object_count == 0:
        issues.add("error", "NO_EXPORTABLE_OBJECTS", "No annotation objects can be exported for the selected format.")

    return AnnotationExportPrecheckResponse(
        dataset_id=dataset_id,
        format=payload.format,
        sample_count=len(samples),
        annotated_sample_count=annotated_sample_count,
        exportable_object_count=exportable_object_count,
        skipped_object_count=skipped_object_count,
        class_map=class_map,
        issues=issues.visible_issues(),
        error_count=issues.counts["error"],
        warning_count=issues.counts["warning"],
        info_count=issues.counts["info"],
        truncated_issue_count=issues.truncated_count(),
        blocked=issues.counts["error"] > 0,
    )


def _check_split_leakage(samples: Iterable[Sample], issues: _IssueCollector) -> None:
    by_hash: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        split_name = (sample.split or "").strip()
        if sample.file_hash and split_name in {"train", "val", "test"}:
            by_hash[sample.file_hash].append(sample)
    for group in by_hash.values():
        splits = {(sample.split or "").strip() for sample in group}
        if len(splits) < 2:
            continue
        sample = group[0]
        issues.add(
            "error",
            "SPLIT_LEAKAGE",
            f"Identical file content appears across splits: {', '.join(sorted(splits))}.",
            sample_id=sample.id,
            sample_path=sample.relative_path,
        )


def _filtered_image_samples(
    session: Session,
    dataset_id: int,
    payload: AnnotationExportPrecheckRequest,
    issues: _IssueCollector,
):
    query = payload.sample_query
    if query.file_type and query.file_type != "image":
        issues.add("error", "UNSUPPORTED_FILE_TYPE", "Annotation export only supports image samples.")
        return []
    return sample_service.get_filtered_samples(
        session,
        dataset_id,
        search=query.search,
        file_type="image",
        file_status=query.file_status,
        tag=query.tag,
        split=query.split,
        review_status=query.review_status,
        sample_ids=query.sample_ids,
        sort_by=query.sort_by,
        sort_order=query.sort_order,
    )


def _check_annotation(
    export_format: str,
    annotation: AnnotationRead,
    image_width: int,
    image_height: int,
    *,
    sample_id: int,
    sample_path: str,
    issues: _IssueCollector,
) -> str:
    if not annotation.label.strip():
        issues.add(
            "error",
            "ANNOTATION_LABEL_REQUIRED",
            "Annotation label is required.",
            sample_id=sample_id,
            sample_path=sample_path,
            annotation_id=annotation.id,
        )
        return "skipped"
    if any(ord(character) < 32 for character in annotation.label):
        issues.add(
            "error",
            "INVALID_CLASS_NAME",
            "Annotation labels cannot contain control characters.",
            sample_id=sample_id,
            sample_path=sample_path,
            annotation_id=annotation.id,
        )
        return "skipped"

    if not _basic_geometry_is_valid(annotation, image_width, image_height, sample_id, sample_path, issues):
        return "skipped"

    if export_format in LABELME_FORMATS:
        return "exportable"

    if export_format in DETECTION_FORMATS:
        if annotation.shape_type == "rectangle":
            return "exportable"
        if annotation.shape_type == "polygon":
            issues.add(
                "warning",
                "POLYGON_TO_BBOX",
                "Polygon annotation will be exported as its bounding box.",
                sample_id=sample_id,
                sample_path=sample_path,
                annotation_id=annotation.id,
            )
            return "exportable"
        return _incompatible_shape(annotation, sample_id, sample_path, issues)

    if export_format in SEGMENTATION_FORMATS:
        if annotation.shape_type == "polygon":
            return "exportable"
        if annotation.shape_type == "rectangle":
            issues.add(
                "warning",
                "RECTANGLE_TO_POLYGON",
                "Rectangle annotation will be exported as a four-point polygon.",
                sample_id=sample_id,
                sample_path=sample_path,
                annotation_id=annotation.id,
            )
            return "exportable"
        return _incompatible_shape(annotation, sample_id, sample_path, issues)

    issues.add(
        "error",
        "UNSUPPORTED_EXPORT_FORMAT",
        f"Unsupported annotation export format: {export_format}",
        sample_id=sample_id,
        sample_path=sample_path,
        annotation_id=annotation.id,
    )
    return "skipped"


def _basic_geometry_is_valid(
    annotation: AnnotationRead,
    image_width: int,
    image_height: int,
    sample_id: int,
    sample_path: str,
    issues: _IssueCollector,
) -> bool:
    try:
        _validate_shape_geometry(annotation)
        if not points_within_image(annotation.points, image_width, image_height):
            issues.add(
                "error",
                "COORDINATES_OUT_OF_BOUNDS",
                "Annotation coordinates exceed image bounds.",
                sample_id=sample_id,
                sample_path=sample_path,
                annotation_id=annotation.id,
            )
            return False
    except ValueError as exc:
        issues.add(
            "error",
            "INVALID_GEOMETRY",
            str(exc),
            sample_id=sample_id,
            sample_path=sample_path,
            annotation_id=annotation.id,
        )
        return False
    return True


def _validate_shape_geometry(annotation: AnnotationRead) -> None:
    if annotation.shape_type == "rectangle":
        rectangle_to_bbox(annotation.points)
        return
    if annotation.shape_type == "polygon":
        polygon_to_bbox(annotation.points)
        if polygon_area(annotation.points) <= 0:
            raise ValueError("Polygon area must be positive.")
        return
    if annotation.shape_type == "point":
        if len(annotation.points) != 2:
            raise ValueError("Point annotations require exactly 2 coordinates.")
        pair_points(annotation.points)
        return
    if annotation.shape_type == "points":
        pair_points(annotation.points)
        return
    raise ValueError(f"Unsupported shape type: {annotation.shape_type}")


def _incompatible_shape(
    annotation: AnnotationRead,
    sample_id: int,
    sample_path: str,
    issues: _IssueCollector,
) -> str:
    issues.add(
        "warning",
        "INCOMPATIBLE_SHAPE_SKIPPED",
        f"{annotation.shape_type} annotation is not compatible with the selected export format.",
        sample_id=sample_id,
        sample_path=sample_path,
        annotation_id=annotation.id,
    )
    return "skipped"


def _build_class_map(labels: Iterable[str]) -> list[AnnotationClassMapItem]:
    result: list[AnnotationClassMapItem] = []
    for yolo_id, name in enumerate(sorted({label.strip() for label in labels if label.strip()})):
        result.append(
            AnnotationClassMapItem(
                name=name,
                id=yolo_id,
                coco_id=yolo_id + 1,
                yolo_id=yolo_id,
            )
        )
    return result
