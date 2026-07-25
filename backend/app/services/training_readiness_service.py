from collections import Counter

from sqlmodel import Session, select

from app.core.workflow import TASK_CAPABILITIES
from app.models.sample import Sample
from app.schemas.training_readiness import TrainingReadinessReport
from app.services import dataset_service, quality_service


EXPORT_FORMATS_BY_TASK: dict[str, tuple[list[str], list[str]]] = {
    "detection": (
        ["coco_detection", "yolo_detection", "voc"],
        ["labelme", "coco_segmentation", "yolo_segmentation"],
    ),
    "segmentation": (
        ["coco_segmentation", "yolo_segmentation", "labelme"],
        ["coco_detection", "yolo_detection", "voc"],
    ),
    "classification": (
        ["csv"],
        ["manifest"],
    ),
}


def build_training_readiness_report(
    session: Session,
    dataset_id: int,
) -> TrainingReadinessReport:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    quality = quality_service.build_quality_report(session, dataset_id)
    samples = session.exec(
        select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)
    ).all()
    scoped_samples = (
        samples
        if dataset.task_type == "classification"
        else [sample for sample in samples if sample.file_type == "image"]
    )

    split_counts = Counter(
        (sample.split or "unassigned").strip() or "unassigned"
        for sample in scoped_samples
    )
    split_covered_sample_count = len(scoped_samples) - split_counts["unassigned"]
    split_coverage_percent = (
        round(split_covered_sample_count / len(scoped_samples) * 100, 1)
        if scoped_samples
        else 0.0
    )

    completed_sample_count = (
        quality.samples_with_objects_count
        if dataset.task_type == "classification"
        else (
            quality.annotation_progress_counts.get("completed_with_objects", 0)
            + quality.confirmed_empty_sample_count
        )
    )
    pending_sample_count = max(len(scoped_samples) - completed_sample_count, 0)
    pending_review_count = quality.review_status_counts.get("in_review", 0)
    rejected_sample_count = quality.review_status_counts.get("rejected", 0)

    capabilities = TASK_CAPABILITIES.get(dataset.task_type)
    if capabilities is None or quality.error_count > 0:
        readiness_status = "blocked"
    elif (
        pending_sample_count > 0
        or pending_review_count > 0
        or rejected_sample_count > 0
        or split_counts["unassigned"] > 0
        or quality.warning_count > 0
    ):
        readiness_status = "needs_attention"
    else:
        readiness_status = "ready"

    compatible_formats, advanced_formats = EXPORT_FORMATS_BY_TASK.get(
        dataset.task_type,
        (["manifest"], []),
    )
    default_format = (
        str(capabilities["default_export_format"])
        if capabilities is not None
        else "manifest"
    )
    task_label = (
        str(capabilities["label"])
        if capabilities is not None
        else f"旧任务类型：{dataset.task_type}"
    )

    return TrainingReadinessReport(
        dataset_id=dataset_id,
        generated_at=quality.generated_at,
        task_type=dataset.task_type,
        task_label=task_label,
        status=readiness_status,
        recommended_export_format=default_format,
        compatible_export_formats=compatible_formats,
        advanced_export_formats=advanced_formats,
        scoped_sample_count=len(scoped_samples),
        completed_sample_count=completed_sample_count,
        confirmed_empty_sample_count=quality.confirmed_empty_sample_count,
        pending_sample_count=pending_sample_count,
        pending_review_count=pending_review_count,
        rejected_sample_count=rejected_sample_count,
        blocking_issue_count=quality.error_count,
        suggested_fix_count=quality.warning_count,
        notice_count=quality.info_count,
        split_counts=dict(sorted(split_counts.items())),
        split_covered_sample_count=split_covered_sample_count,
        split_coverage_percent=split_coverage_percent,
        last_export_at=None,
    )
