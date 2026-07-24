from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnnotationClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1000)


class AnnotationClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1000)


class AnnotationClassRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    name: str
    color: str | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime
