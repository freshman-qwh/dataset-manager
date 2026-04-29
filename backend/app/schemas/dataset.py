from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    task_type: str | None = Field(default="classification", max_length=80)
    root_path: str | None = Field(default=None, max_length=2000)


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    task_type: str | None = Field(default=None, max_length=80)
    root_path: str | None = Field(default=None, max_length=2000)


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    task_type: str | None
    root_path: str | None
    sample_count: int = 0
    created_at: datetime
    updated_at: datetime
