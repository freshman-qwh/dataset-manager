"""Small named lists of sample references; never owns original files."""
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class SampleCollection(SQLModel, table=True):
    __tablename__ = "sample_collections"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=160)
    kind: str = Field(default="basket", max_length=20, index=True)
    # Deliberately retain references when datasets/samples are removed, so the
    # user can see and remove unavailable entries rather than losing the list.
    dataset_id: int | None = Field(default=None, index=True)
    category_id: int | None = Field(default=None)
    version: int = Field(default=1)
    items_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
