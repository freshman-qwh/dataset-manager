from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.workflow import DatasetTaskType


class DatasetTaskCapabilities(BaseModel):
    label: str
    annotation_mode: str
    allowed_shape_types: list[str]
    default_export_format: str
    supported: bool
    unsupported_reason: str | None = None


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    task_type: DatasetTaskType = "detection"
    root_path: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=500)
    modality: str | None = Field(default=None, max_length=120)
    license: str | None = Field(default=None, max_length=160)
    owner: str | None = Field(default=None, max_length=160)
    project: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    auto_scan_on_open: bool = False


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    task_type: DatasetTaskType | None = None
    root_path: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=500)
    modality: str | None = Field(default=None, max_length=120)
    license: str | None = Field(default=None, max_length=160)
    owner: str | None = Field(default=None, max_length=160)
    project: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    auto_scan_on_open: bool | None = None

    @field_validator("task_type")
    @classmethod
    def task_type_cannot_be_null(cls, value: DatasetTaskType | None) -> DatasetTaskType | None:
        if value is None:
            raise ValueError("task_type cannot be null when provided")
        return value


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    task_type: str
    task_capabilities: DatasetTaskCapabilities
    root_path: str | None
    source: str | None
    modality: str | None
    license: str | None
    owner: str | None
    project: str | None
    notes: str | None
    auto_scan_on_open: bool
    sample_count: int = 0
    created_at: datetime
    updated_at: datetime
