from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.annotation_export import AnnotationClassMapItem, AnnotationExportSampleQuery
from app.schemas.quality import QualityIssue


TrainingReadinessStatus = Literal["blocked", "needs_attention", "ready"]
TrainingReadinessScope = Literal["filtered", "all", "split", "selected"]
TrainingReadinessExportFormat = Literal[
    "labelme",
    "coco_detection",
    "coco_segmentation",
    "yolo_detection",
    "yolo_segmentation",
    "voc",
    "csv",
    "manifest",
]


class TrainingReadinessConfigRequest(BaseModel):
    format: TrainingReadinessExportFormat
    scope: TrainingReadinessScope
    split: str | None = Field(default=None, max_length=40)
    include_empty: bool = False
    sample_query: AnnotationExportSampleQuery = Field(default_factory=AnnotationExportSampleQuery)
    class_map: list[AnnotationClassMapItem] = Field(default_factory=list)


class TrainingReadinessConfig(BaseModel):
    task_type: str
    format: TrainingReadinessExportFormat
    scope: TrainingReadinessScope
    split: str | None = None
    include_empty: bool
    sample_query: AnnotationExportSampleQuery
    class_map: list[AnnotationClassMapItem] = Field(default_factory=list)
    saved_at: datetime
    last_export_at: datetime | None = None


class TrainingReadinessReport(BaseModel):
    dataset_id: int
    generated_at: datetime
    task_type: str
    task_label: str
    status: TrainingReadinessStatus
    recommended_export_format: str
    compatible_export_formats: list[str] = Field(default_factory=list)
    advanced_export_formats: list[str] = Field(default_factory=list)
    scoped_sample_count: int
    completed_sample_count: int
    confirmed_empty_sample_count: int
    pending_sample_count: int
    pending_review_count: int
    rejected_sample_count: int
    blocking_issue_count: int
    suggested_fix_count: int
    notice_count: int
    truncated_issue_count: int
    issues: list[QualityIssue] = Field(default_factory=list)
    split_counts: dict[str, int] = Field(default_factory=dict)
    split_covered_sample_count: int
    split_coverage_percent: float
    last_export_at: datetime | None = None
    last_config: TrainingReadinessConfig | None = None
