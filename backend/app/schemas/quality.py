from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


QualityIssueSeverity = Literal["error", "warning", "info"]


class QualityIssue(BaseModel):
    severity: QualityIssueSeverity
    code: str
    title: str
    message: str
    sample_id: int | None = None
    sample_path: str | None = None
    annotation_id: int | None = None
    related_sample_ids: list[int] = Field(default_factory=list)
    related_annotation_ids: list[int] = Field(default_factory=list)


class DatasetQualityReport(BaseModel):
    dataset_id: int
    generated_at: datetime
    sample_count: int
    image_sample_count: int
    samples_with_objects_count: int
    confirmed_empty_sample_count: int
    annotation_progress_counts: dict[str, int] = Field(default_factory=dict)
    annotation_count: int
    issue_count: int
    error_count: int
    warning_count: int
    info_count: int
    truncated_issue_count: int
    check_counts: dict[str, int] = Field(default_factory=dict)
    review_status_counts: dict[str, int] = Field(default_factory=dict)
    class_counts: dict[str, int] = Field(default_factory=dict)
    split_class_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    issues: list[QualityIssue] = Field(default_factory=list)
