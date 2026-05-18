from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class Annotation(SQLModel, table=True):
    __tablename__ = "annotations"

    id: int | None = Field(default=None, primary_key=True)
    sample_id: int = Field(foreign_key="samples.id", index=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    tag_id: int | None = Field(default=None, foreign_key="tags.id", index=True)
    label: str = Field(index=True, max_length=120)
    shape_type: str = Field(index=True, max_length=40)
    points_json: str
    flags_json: str | None = Field(default=None)
    attributes_json: str | None = Field(default=None)
    group_id: int | None = Field(default=None, index=True)
    z_order: int = Field(default=0)
    locked: bool = Field(default=False)
    hidden: bool = Field(default=False)
    source: str = Field(default="manual", max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
