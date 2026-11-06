from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称不能为空。")
        return value.strip()


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("名称不能为空。")
        return value.strip()


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    dataset_count: int = 0


class CategoryCreate(ProjectCreate):
    pass


class CategoryUpdate(ProjectUpdate):
    pass


class CategoryRead(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dataset_id: int
    sample_count: int = 0
    normal_count: int = 0
    anomaly_count: int = 0
    cover_sample_id: int | None = None
    cover_file_hash: str | None = None


class BatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    captured_at: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("批次名称不能为空。")
        return value.strip()


class BatchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    captured_at: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("批次名称不能为空。")
        return value.strip()


class BatchRead(BatchCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dataset_id: int
    code: str
    sample_count: int = 0


class DatasetOrganizationRead(BaseModel):
    project: ProjectRead | None = None
    categories: list[CategoryRead]
    batches: list[BatchRead]


class OrganizationAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_ids: list[int] = Field(min_length=1, max_length=10000)
    category_id: int | None = Field(default=None, gt=0)
    batch_id: int | None = Field(default=None, gt=0)


class OrganizationAssignRead(BaseModel):
    updated_count: int
    dataset_revision: int
