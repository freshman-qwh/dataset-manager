"""Read-only content for the automatically generated dataset card."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.dataset import DatasetRead


class DatasetCardSplits(BaseModel):
    train: int
    val: int
    test: int
    unassigned: int


class DatasetCardSummary(BaseModel):
    sample_count: int
    image_count: int
    normal_count: int
    anomaly_count: int
    pending_count: int
    untriaged_count: int
    unavailable_count: int
    mask_count: int
    category_count: int
    batch_count: int
    splits: DatasetCardSplits


class DatasetCardCategory(BaseModel):
    id: int
    name: str
    sample_count: int
    normal_count: int
    anomaly_count: int


class DatasetCardPreview(BaseModel):
    sample_id: int
    filename: str
    file_hash: str
    category_name: str | None
    label: Literal["normal", "anomaly", "pending"] | None


class DatasetCardRead(BaseModel):
    dataset: DatasetRead
    generated_at: datetime
    summary: DatasetCardSummary
    categories: list[DatasetCardCategory]
    preview_samples: list[DatasetCardPreview]
