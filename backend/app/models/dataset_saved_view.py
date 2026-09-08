from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class DatasetSavedView(SQLModel, table=True):
    __tablename__ = "dataset_saved_views"
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_saved_views_name"),
        Index("ix_dataset_saved_views_dataset_updated", "dataset_id", "updated_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    name: str = Field(min_length=1, max_length=160)
    task_type: str = Field(max_length=80)
    queue_scope: str = Field(default="current_filter", max_length=40)
    query_json: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
