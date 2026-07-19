from typing import Literal

DatasetTaskType = Literal["detection", "segmentation", "classification"]
AnnotationProgress = Literal[
    "not_started",
    "in_progress",
    "completed_empty",
    "completed_with_objects",
]
ReviewStatus = Literal["not_reviewed", "in_review", "approved", "rejected"]

DATASET_TASK_TYPES: tuple[DatasetTaskType, ...] = (
    "detection",
    "segmentation",
    "classification",
)
ANNOTATION_PROGRESS_VALUES: tuple[AnnotationProgress, ...] = (
    "not_started",
    "in_progress",
    "completed_empty",
    "completed_with_objects",
)
REVIEW_STATUS_VALUES: tuple[ReviewStatus, ...] = (
    "not_reviewed",
    "in_review",
    "approved",
    "rejected",
)


TASK_CAPABILITIES: dict[str, dict[str, object]] = {
    "detection": {
        "label": "目标检测",
        "annotation_mode": "geometry",
        "allowed_shape_types": ["rectangle"],
        "default_export_format": "coco_detection",
        "supported": True,
        "unsupported_reason": None,
    },
    "segmentation": {
        "label": "多边形分割",
        "annotation_mode": "geometry",
        "allowed_shape_types": ["polygon"],
        "default_export_format": "coco_segmentation",
        "supported": True,
        "unsupported_reason": None,
    },
    "classification": {
        "label": "分类整理",
        "annotation_mode": "sample_tags",
        "allowed_shape_types": [],
        "default_export_format": "csv",
        "supported": True,
        "unsupported_reason": None,
    },
}


def task_capabilities(task_type: str | None) -> dict[str, object]:
    if task_type in TASK_CAPABILITIES:
        return TASK_CAPABILITIES[task_type].copy()
    legacy_name = task_type or "未设置"
    return {
        "label": f"旧任务类型：{legacy_name}",
        "annotation_mode": "unsupported",
        "allowed_shape_types": [],
        "default_export_format": "manifest",
        "supported": False,
        "unsupported_reason": "该旧任务类型不再驱动标注流程，请在数据集设置中改为目标检测、多边形分割或分类整理。",
    }
