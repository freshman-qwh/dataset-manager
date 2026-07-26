from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Index, UniqueConstraint, func
from sqlmodel import Field, Relationship, SQLModel

from app.models.dataset import utc_now

if TYPE_CHECKING:
    from app.models.dataset import Dataset
    from app.models.tag import Tag


class SampleTagLink(SQLModel, table=True):
    __tablename__ = "sample_tag_links"
    __table_args__ = (
        Index("ix_sample_tag_links_tag_sample", "tag_id", "sample_id"),
    )

    sample_id: int | None = Field(default=None, foreign_key="samples.id", primary_key=True)
    tag_id: int | None = Field(default=None, foreign_key="tags.id", primary_key=True)


class Sample(SQLModel, table=True):
    __tablename__ = "samples"
    __table_args__ = (
        UniqueConstraint("dataset_id", "absolute_path", name="uq_samples_dataset_path"),
        Index(
            "ix_samples_dataset_filter",
            "dataset_id",
            "file_type",
            "file_status",
            "annotation_progress",
        ),
        Index(
            "ix_samples_dataset_split_review",
            "dataset_id",
            "split",
            "review_status",
        ),
        Index("ix_samples_dataset_hash", "dataset_id", "file_hash"),
        Index("ix_samples_dataset_created", "dataset_id", "created_at"),
        Index("ix_samples_dataset_filename", "dataset_id", "filename"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    filename: str = Field(index=True, max_length=512)
    absolute_path: str = Field(max_length=2000)
    relative_path: str = Field(index=True, max_length=2000)
    file_size: int = Field(default=0, ge=0)
    extension: str = Field(index=True, max_length=32)
    file_type: str = Field(index=True, max_length=32)
    mime_type: str | None = Field(default=None, max_length=120)
    file_hash: str = Field(index=True, max_length=128)
    file_status: str = Field(default="normal", index=True, max_length=40)
    file_modified_at: datetime | None = Field(default=None)
    last_scanned_at: datetime | None = Field(default=None)
    split: str | None = Field(default=None, max_length=40)
    annotation_progress: str = Field(default="not_started", index=True, max_length=40)
    review_status: str = Field(default="not_reviewed", index=True, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)
    metadata_json: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    dataset: "Dataset" = Relationship(back_populates="samples")
    tags: list["Tag"] = Relationship(back_populates="samples", link_model=SampleTagLink)


Index(
    "ix_samples_dataset_filename_lower",
    Sample.dataset_id,
    func.lower(Sample.filename),
    Sample.id,
)
