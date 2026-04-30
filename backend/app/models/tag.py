from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.dataset import utc_now
from app.models.sample import SampleTagLink

if TYPE_CHECKING:
    from app.models.dataset import Dataset
    from app.models.sample import Sample


class Tag(SQLModel, table=True):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_tags_dataset_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    name: str = Field(index=True, min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1000)
    parent_id: int | None = Field(default=None, index=True)
    aliases_json: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)

    dataset: "Dataset" = Relationship(back_populates="tags")
    samples: list["Sample"] = Relationship(back_populates="tags", link_model=SampleTagLink)
