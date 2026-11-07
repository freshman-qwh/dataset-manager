"""Read-only workpiece views and registered training eligibility."""

from pydantic import BaseModel, Field

from app.schemas.sample import SampleRead


class WorkpieceIsolationRead(BaseModel):
    total: int = Field(ge=1)
    normal_candidate: bool
    reasons: dict[str, int] = Field(default_factory=dict)


class WorkpieceViewsRead(BaseModel):
    dataset_id: int
    anchor_sample_id: int
    capture_group_id: str | None
    capture_batch_id: str | None
    dataset_revision: int
    items: list[SampleRead]
    total: int = Field(ge=1)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=24)
    isolation: WorkpieceIsolationRead
