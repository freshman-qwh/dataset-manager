from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class AnnotationClass(SQLModel, table=True):
    __tablename__ = "annotation_classes"
    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_annotation_classes_dataset_name"),)

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    name: str = Field(index=True, min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
