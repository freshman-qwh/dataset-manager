from datetime import datetime

from pydantic import BaseModel, Field

from app.core.workflow import ReviewStatus


class AnnotationBase(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    tag_id: int | None = None
    shape_type: str = Field(pattern="^(rectangle|polygon|point|points)$")
    points: list[float] = Field(min_length=2)
    flags: dict[str, bool] = Field(default_factory=dict)
    attributes: dict[str, object] = Field(default_factory=dict)
    group_id: int | None = None
    z_order: int = 0
    locked: bool = False
    hidden: bool = False
    source: str = Field(default="manual", max_length=40)
    notes: str | None = Field(default=None, max_length=2000)


class AnnotationCreate(AnnotationBase):
    pass


class AnnotationRead(AnnotationBase):
    id: int
    sample_id: int
    dataset_id: int
    created_at: datetime
    updated_at: datetime


class AnnotationReplaceRequest(BaseModel):
    annotations: list[AnnotationCreate] = Field(default_factory=list)
    review_status: ReviewStatus | None = None
    sync_sample_tags: bool = True
