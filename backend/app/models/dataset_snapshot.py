from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class DatasetSnapshot(SQLModel, table=True):
    __tablename__ = "dataset_snapshots"
    __table_args__ = (
        UniqueConstraint("dataset_id", "artifact_path", name="uq_dataset_snapshots_artifact"),
        Index("ix_dataset_snapshots_dataset_created", "dataset_id", "created_at"),
        Index("ix_dataset_snapshots_dataset_revision", "dataset_id", "dataset_revision"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    dataset_revision: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=160)
    artifact_path: str = Field(max_length=1000)
    content_sha256: str = Field(max_length=64, index=True)
    sample_count: int = Field(default=0, ge=0)
    annotation_count: int = Field(default=0, ge=0)
    class_count: int = Field(default=0, ge=0)
    query_json: str
    export_config_json: str
    created_at: datetime = Field(default_factory=utc_now)
