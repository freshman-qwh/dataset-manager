from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.quality import QualityIssue


TrainingReadinessStatus = Literal["blocked", "needs_attention", "ready"]


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
