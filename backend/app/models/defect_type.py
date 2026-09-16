from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class DefectType(SQLModel, table=True):
    __tablename__ = "defect_types"
    __table_args__ = (
        UniqueConstraint("dataset_id", "code", name="uq_defect_types_dataset_code"),
        Index("ix_defect_types_dataset_parent", "dataset_id", "parent_id", "is_active"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    name: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=80)
    parent_id: int | None = Field(default=None, foreign_key="defect_types.id", index=True)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SampleDefectLink(SQLModel, table=True):
    __tablename__ = "sample_defect_links"
    __table_args__ = (
        Index("ix_sample_defect_links_type_sample", "defect_type_id", "sample_id"),
    )

    sample_id: int = Field(foreign_key="samples.id", primary_key=True)
    defect_type_id: int = Field(foreign_key="defect_types.id", primary_key=True)
