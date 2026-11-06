"""Business organization, independent from disk folders and geometry labels."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DatasetCategory(SQLModel, table=True):
    __tablename__ = "dataset_categories"
    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_dataset_categories_name"),)

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    name: str = Field(max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class DatasetBatch(SQLModel, table=True):
    __tablename__ = "dataset_batches"
    __table_args__ = (UniqueConstraint("dataset_id", "code", name="uq_dataset_batches_code"),)

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    name: str = Field(max_length=160)
    code: str = Field(default_factory=lambda: "batch-" + uuid4().hex, max_length=160)
    captured_at: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
