from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.workflow import AnnotationProgress, DatasetTaskType, ReviewStatus


SavedViewQueueScope = Literal["all_pending", "current_filter", "current_split"]
SavedViewSortField = Literal[
    "created_at",
    "updated_at",
    "filename",
    "relative_path",
    "file_size",
    "extension",
    "file_type",
    "file_status",
    "split",
    "review_status",
    "annotation_progress",
]


class DatasetSavedViewQuery(BaseModel):
    search: str | None = Field(default=None, max_length=300)
    file_type: str | None = Field(default=None, max_length=40)
    file_status: str | None = Field(default=None, max_length=40)
    tag: str | None = Field(default=None, max_length=160)
    split: str | None = Field(default=None, max_length=40)
    review_status: ReviewStatus | None = None
    annotation_progress: AnnotationProgress | None = None
    sort_by: SavedViewSortField = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"

    @field_validator("search", "file_type", "file_status", "tag", "split")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None


class DatasetSavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    queue_scope: SavedViewQueueScope = "current_filter"
    sample_query: DatasetSavedViewQuery = Field(default_factory=DatasetSavedViewQuery)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Saved view name cannot be empty.")
        return normalized

    @model_validator(mode="after")
    def validate_current_split_scope(self) -> "DatasetSavedViewCreate":
        if self.queue_scope == "current_split" and not self.sample_query.split:
            raise ValueError("current_split queue scope requires a split filter.")
        return self


class DatasetSavedViewRead(BaseModel):
    id: int
    dataset_id: int
    name: str
    task_type: DatasetTaskType | str
    queue_scope: SavedViewQueueScope
    sample_query: DatasetSavedViewQuery
    created_at: datetime
    updated_at: datetime
