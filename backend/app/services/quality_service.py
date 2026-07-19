from collections import Counter, defaultdict
from pathlib import Path

from sqlmodel import Session, select

from app.models.annotation import Annotation
from app.models.dataset import utc_now
from app.models.sample import Sample
from app.schemas.annotation import AnnotationRead
from app.schemas.quality import DatasetQualityReport, QualityIssue
from app.services import annotation_service, dataset_service
from app.services.annotation_geometry import (
    BBox,
    pair_points,
    points_within_image,
    polygon_area,
    polygon_to_bbox,
    rectangle_to_bbox,
)
from app.utils.image_size import read_image_size

DEFAULT_ISSUE_LIMIT = 500
TRAINING_SPLITS = {"train", "val", "test"}
STANDARD_REVIEW_STATUSES = ("not_reviewed", "in_review", "approved", "rejected")

ISSUE_COPY: dict[str, tuple[str, str]] = {
    "FILE_UNAVAILABLE": ("文件不可用", "样本文件缺失或当前进程没有读取权限。"),
    "EMPTY_ANNOTATIONS": ("图片没有标注对象", "该图片还没有任何几何标注。"),
    "IMAGE_SIZE_UNAVAILABLE": ("无法读取图片尺寸", "无法读取图片宽高，不能验证标注边界。"),
    "INVALID_ANNOTATION_GEOMETRY": ("标注几何无效", "对象坐标数量、形状或面积不符合要求。"),
    "COORDINATES_OUT_OF_BOUNDS": ("标注坐标越界", "对象坐标超出图片宽高范围。"),
    "DUPLICATE_ANNOTATION": ("疑似重复对象", "同一样本内存在完全相同或高度重叠的同类对象。"),
    "SPLIT_LEAKAGE": ("训练划分泄漏", "相同文件内容同时出现在多个 train/val/test 划分中。"),
    "RARE_CLASS": ("极少样本类别", "该类别的对象数量过少，训练与评估结果可能不稳定。"),
    "CLASS_SINGLE_SPLIT": ("类别只出现在单一划分", "该类别没有覆盖多个已使用的训练划分。"),
    "CLASS_SPLIT_IMBALANCE": ("类别在划分间分布偏移", "该类别在各 split 的占比明显偏离数据集整体分布。"),
    "REJECTED_SAMPLE": ("存在已拒绝样本", "该样本的审查状态为已拒绝，不应直接进入训练导出。"),
    "REVIEW_PENDING": ("存在待审核样本", "该样本已有标注，但仍处于待审核状态。"),
}


class _IssueCollector:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._visible: dict[str, list[QualityIssue]] = {"error": [], "warning": [], "info": []}
        self.severity_counts: Counter[str] = Counter()
        self.code_counts: Counter[str] = Counter()

    def add(
        self,
        severity: str,
        code: str,
        *,
        sample: Sample | None = None,
        annotation_id: int | None = None,
        related_sample_ids: list[int] | None = None,
        related_annotation_ids: list[int] | None = None,
        message: str | None = None,
    ) -> None:
        self.severity_counts[severity] += 1
        self.code_counts[code] += 1
        title, default_message = ISSUE_COPY[code]
        issue = QualityIssue(
            severity=severity,
            code=code,
            title=title,
            message=message or default_message,
            sample_id=sample.id if sample else None,
            sample_path=sample.relative_path if sample else None,
            annotation_id=annotation_id,
            related_sample_ids=related_sample_ids or [],
            related_annotation_ids=related_annotation_ids or [],
        )
        if len(self._visible[severity]) < self.limit:
            self._visible[severity].append(issue)

    def visible(self) -> list[QualityIssue]:
        result: list[QualityIssue] = []
        for severity in ("error", "warning", "info"):
            remaining = self.limit - len(result)
            if remaining <= 0:
                break
            result.extend(self._visible[severity][:remaining])
        return result

    @property
    def total(self) -> int:
        return sum(self.severity_counts.values())


def build_quality_report(
    session: Session,
    dataset_id: int,
    *,
    issue_limit: int = DEFAULT_ISSUE_LIMIT,
) -> DatasetQualityReport:
    dataset_service.get_dataset_or_404(session, dataset_id)
    samples = session.exec(
        select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.relative_path, Sample.id)
    ).all()
    image_samples = [sample for sample in samples if sample.file_type == "image"]
    sample_by_id = {sample.id: sample for sample in image_samples if sample.id is not None}
    annotations = session.exec(
        select(Annotation)
        .where(Annotation.dataset_id == dataset_id)
        .order_by(Annotation.sample_id, Annotation.z_order, Annotation.id)
    ).all()
    annotations_by_sample: dict[int, list[AnnotationRead]] = defaultdict(list)
    for annotation in annotations:
        if annotation.sample_id in sample_by_id:
            annotations_by_sample[annotation.sample_id].append(annotation_service.to_annotation_read(annotation))

    issues = _IssueCollector(max(1, min(issue_limit, 1000)))
    review_status_counts = Counter((sample.review_status or "not_reviewed") for sample in image_samples)
    for status in STANDARD_REVIEW_STATUSES:
        if review_status_counts[status] == 0:
            del review_status_counts[status]

    class_counts: Counter[str] = Counter()
    split_class_counts: dict[str, Counter[str]] = defaultdict(Counter)
    annotated_sample_count = 0

    for sample in image_samples:
        sample_id = sample.id or 0
        sample_annotations = annotations_by_sample.get(sample_id, [])
        if sample.file_status in {"missing", "permission_denied"}:
            issues.add("error", "FILE_UNAVAILABLE", sample=sample)
            continue
        if not sample_annotations:
            issues.add("warning", "EMPTY_ANNOTATIONS", sample=sample)
            if sample.review_status == "rejected":
                issues.add("info", "REJECTED_SAMPLE", sample=sample)
            continue

        annotated_sample_count += 1
        if sample.review_status == "rejected":
            issues.add("warning", "REJECTED_SAMPLE", sample=sample)
        elif sample.review_status in {"not_reviewed", "in_review"}:
            issues.add("info", "REVIEW_PENDING", sample=sample)

        image_size = read_image_size(Path(sample.absolute_path))
        if image_size is None:
            issues.add("error", "IMAGE_SIZE_UNAVAILABLE", sample=sample)

        for annotation in sample_annotations:
            label = annotation.label.strip()
            if label:
                class_counts[label] += 1
                split_name = (sample.split or "unassigned").strip() or "unassigned"
                split_class_counts[split_name][label] += 1
            _check_geometry(annotation, sample, image_size, issues)
        _check_duplicate_annotations(sample, sample_annotations, issues)

    _check_split_leakage(image_samples, issues)
    _check_class_distribution(class_counts, split_class_counts, issues)

    visible_issues = issues.visible()
    return DatasetQualityReport(
        dataset_id=dataset_id,
        generated_at=utc_now(),
        sample_count=len(samples),
        image_sample_count=len(image_samples),
        annotated_sample_count=annotated_sample_count,
        annotation_count=sum(len(items) for items in annotations_by_sample.values()),
        issue_count=issues.total,
        error_count=issues.severity_counts["error"],
        warning_count=issues.severity_counts["warning"],
        info_count=issues.severity_counts["info"],
        truncated_issue_count=issues.total - len(visible_issues),
        check_counts=dict(sorted(issues.code_counts.items())),
        review_status_counts=dict(sorted(review_status_counts.items())),
        class_counts=dict(sorted(class_counts.items())),
        split_class_counts={
            split_name: dict(sorted(counts.items()))
            for split_name, counts in sorted(split_class_counts.items())
        },
        issues=visible_issues,
    )


def _check_geometry(
    annotation: AnnotationRead,
    sample: Sample,
    image_size: tuple[int, int] | None,
    issues: _IssueCollector,
) -> None:
    try:
        if annotation.shape_type == "rectangle":
            rectangle_to_bbox(annotation.points)
        elif annotation.shape_type == "polygon":
            polygon_to_bbox(annotation.points)
            if polygon_area(annotation.points) <= 0:
                raise ValueError("Polygon area must be positive.")
        elif annotation.shape_type == "point":
            if len(pair_points(annotation.points)) != 1:
                raise ValueError("Point annotations require exactly one point.")
        elif annotation.shape_type == "points":
            pair_points(annotation.points)
        else:
            raise ValueError("Unsupported shape type.")
    except ValueError:
        issues.add(
            "error",
            "INVALID_ANNOTATION_GEOMETRY",
            sample=sample,
            annotation_id=annotation.id,
            related_annotation_ids=[annotation.id],
        )
        return

    if image_size is not None and not points_within_image(annotation.points, image_size[0], image_size[1]):
        issues.add(
            "error",
            "COORDINATES_OUT_OF_BOUNDS",
            sample=sample,
            annotation_id=annotation.id,
            related_annotation_ids=[annotation.id],
        )


def _check_duplicate_annotations(
    sample: Sample,
    annotations: list[AnnotationRead],
    issues: _IssueCollector,
) -> None:
    for left_index, left in enumerate(annotations):
        for right in annotations[left_index + 1 :]:
            if left.label.strip().casefold() != right.label.strip().casefold():
                continue
            exact = left.shape_type == right.shape_type and left.points == right.points
            overlap = False
            if not exact:
                left_bbox = _annotation_bbox(left)
                right_bbox = _annotation_bbox(right)
                overlap = left_bbox is not None and right_bbox is not None and _bbox_iou(left_bbox, right_bbox) >= 0.95
            if exact or overlap:
                related_ids = [item for item in (left.id, right.id) if item]
                issues.add(
                    "warning",
                    "DUPLICATE_ANNOTATION",
                    sample=sample,
                    annotation_id=related_ids[0] if related_ids else None,
                    related_annotation_ids=related_ids,
                )


def _annotation_bbox(annotation: AnnotationRead) -> BBox | None:
    try:
        if annotation.shape_type == "rectangle":
            return rectangle_to_bbox(annotation.points)
        if annotation.shape_type == "polygon":
            return polygon_to_bbox(annotation.points)
    except ValueError:
        return None
    return None


def _bbox_iou(left: BBox, right: BBox) -> float:
    intersection_width = max(0.0, min(left.x_max, right.x_max) - max(left.x_min, right.x_min))
    intersection_height = max(0.0, min(left.y_max, right.y_max) - max(left.y_min, right.y_min))
    intersection = intersection_width * intersection_height
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union if union > 0 else 0.0


def _check_split_leakage(samples: list[Sample], issues: _IssueCollector) -> None:
    by_hash: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        split_name = (sample.split or "").strip()
        if sample.file_status == "normal" and sample.file_hash and split_name in TRAINING_SPLITS:
            by_hash[sample.file_hash].append(sample)
    for group in by_hash.values():
        splits = {(sample.split or "").strip() for sample in group}
        if len(splits) < 2:
            continue
        related_ids = [sample.id for sample in group if sample.id is not None]
        issues.add(
            "error",
            "SPLIT_LEAKAGE",
            sample=group[0],
            related_sample_ids=related_ids,
            message=f"相同文件内容出现在 {', '.join(sorted(splits))} 划分中。",
        )


def _check_class_distribution(
    class_counts: Counter[str],
    split_class_counts: dict[str, Counter[str]],
    issues: _IssueCollector,
) -> None:
    rare_threshold = 2
    used_training_splits = {
        split_name for split_name, counts in split_class_counts.items() if split_name in TRAINING_SPLITS and counts
    }
    total_by_split = {
        split_name: sum(split_class_counts[split_name].values())
        for split_name in used_training_splits
    }
    total_training_objects = sum(total_by_split.values())
    for label, count in sorted(class_counts.items()):
        training_label_count = sum(
            split_class_counts[split_name].get(label, 0)
            for split_name in used_training_splits
        )
        if count <= rare_threshold:
            issues.add(
                "warning",
                "RARE_CLASS",
                message=f"类别“{label}”只有 {count} 个对象。",
            )
        class_splits = {
            split_name
            for split_name in used_training_splits
            if split_class_counts[split_name].get(label, 0) > 0
        }
        if len(used_training_splits) >= 2 and len(class_splits) == 1:
            issues.add(
                "warning",
                "CLASS_SINGLE_SPLIT",
                message=f"类别“{label}”只出现在 {next(iter(class_splits))} 划分。",
            )
        elif training_label_count >= 10 and len(class_splits) >= 2 and total_training_objects > 0:
            maximum_delta = max(
                abs(
                    split_class_counts[split_name].get(label, 0) / training_label_count
                    - total_by_split[split_name] / total_training_objects
                )
                for split_name in used_training_splits
            )
            if maximum_delta >= 0.30:
                issues.add(
                    "warning",
                    "CLASS_SPLIT_IMBALANCE",
                    message=f"类别“{label}”在各划分的占比与整体分布最大相差 {maximum_delta:.0%}。",
                )
