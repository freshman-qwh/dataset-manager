from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tag import TagRead


class SampleUpdate(BaseModel):
    split: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None


class BatchSampleUpdate(BaseModel):
    sample_ids: list[int] = Field(min_length=1)
    split: str | None = Field(default=None, max_length=40)
    add_tags: list[str] | None = None
    replace_tags: list[str] | None = None


class BatchSampleUpdateResult(BaseModel):
    dataset_id: int
    requested: int
    updated: int
    skipped: int


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
