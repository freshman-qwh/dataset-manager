"""Paginated, read-only normal/anomaly comparison views."""
from pydantic import BaseModel

from app.schemas.sample import SampleRead


class ComparisonSide(BaseModel):
    items: list[SampleRead]
    total: int
    page: int
    page_size: int


class ComparisonRead(BaseModel):
    dataset_id: int
    category_id: int | None
    batch_id: int | None
    normal: ComparisonSide
    anomaly: ComparisonSide
    excluded_count: int
