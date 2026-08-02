from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.workflow import AnnotationProgress, ReviewStatus
from app.schemas.tag import TagRead


class SampleUpdate(BaseModel):
    split: str | None = Field(default=None, max_length=40)
    annotation_progress: AnnotationProgress | None = None
    review_status: ReviewStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None


class BatchSampleUpdate(BaseModel):
    sample_ids: list[int] = Field(min_length=1)
    split: str | None = Field(default=None, max_length=40)
    annotation_progress: AnnotationProgress | None = None
    review_status: ReviewStatus | None = None
    add_tags: list[str] | None = None
    replace_tags: list[str] | None = None


class BatchSampleUpdateResult(BaseModel):
    dataset_id: int
    requested: int
    updated: int
    skipped: int


class BatchSampleDelete(BaseModel):
    sample_ids: list[int] = Field(min_length=1)


class SampleDeleteResult(BaseModel):
    dataset_id: int
    requested: int
    deleted: int
    skipped: int


class SampleRepairRequest(BaseModel):
    file_path: str = Field(min_length=1)


class MissingSampleRepairRequest(BaseModel):
    root_path: str = Field(min_length=1)
    update_dataset_root: bool = True


class MissingSampleRepairResult(BaseModel):
    dataset_id: int
    root_path: str
    checked: int
    repaired: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class SamplePreview(BaseModel):
    sample_id: int
    file_type: str
    filename: str
    file_url: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)
    preview_row_count: int = 0
    error: str | None = None


class SampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    filename: str
    absolute_path: str
    relative_path: str
    file_size: int
    extension: str
    file_type: str
    mime_type: str | None
    file_hash: str
    file_status: str
    file_modified_at: datetime | None
    last_scanned_at: datetime | None
    split: str | None
    annotation_progress: AnnotationProgress
    review_status: ReviewStatus
    notes: str | None
    metadata: dict[str, object] = Field(default_factory=dict)
    tags: list[TagRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SampleListResponse(BaseModel):
    items: list[SampleRead]
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_order: str
    thumbnail_prefetch_sample_ids: list[int] = Field(default_factory=list)


class SampleNavigationResponse(BaseModel):
    current_sample: SampleRead | None = None
    previous_sample: SampleRead | None = None
    next_sample: SampleRead | None = None
    current_index: int | None = None
    total: int
    remaining: int
    queue_scope: Literal["all_pending", "current_filter", "current_split"]
    sort_by: str
    sort_order: str
