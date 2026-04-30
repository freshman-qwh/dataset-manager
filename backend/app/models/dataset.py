from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.sample import Sample
    from app.models.tag import Tag


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(SQLModel, table=True):
    __tablename__ = "datasets"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    task_type: str | None = Field(default="classification", max_length=80)
    root_path: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=500)
    modality: str | None = Field(default=None, max_length=120)
    license: str | None = Field(default=None, max_length=160)
    owner: str | None = Field(default=None, max_length=160)
    project: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    samples: list["Sample"] = Relationship(back_populates="dataset")
    tags: list["Tag"] = Relationship(back_populates="dataset")
