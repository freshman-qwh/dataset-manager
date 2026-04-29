from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tag import TagRead


class SampleUpdate(BaseModel):
    split: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None


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
    split: str | None
    notes: str | None
    tags: list[TagRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
