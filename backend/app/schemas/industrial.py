from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GroupPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["selected", "directories", "mapping"] = "selected"
    sample_ids: list[int] = Field(default_factory=list, max_length=200)
    capture_group_id: str | None = Field(default=None, max_length=160)
    capture_batch_id: str | None = Field(default=None, max_length=160)
    mapping_text: str | None = Field(default=None, max_length=2_000_000)
    path_column: str = Field(default="relative_path", min_length=1, max_length=160)
    group_column: str = Field(default="capture_group_id", min_length=1, max_length=160)
    batch_column: str = Field(default="capture_batch_id", min_length=1, max_length=160)

    @field_validator("capture_group_id", "capture_batch_id")
    @classmethod
    def clean_identity(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PlanConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation: str = Field(max_length=300)


class FrozenPlanRead(BaseModel):
    plan_id: str
    plan_hash: str
    kind: str
    dataset_id: int
    dataset_revision: int
    expires_at: float
    summary: dict[str, object]
    confirmation: str
    total: int
    page: int
    page_size: int
    rows: list[dict[str, object]]


class ConfirmationRead(BaseModel):
    dataset_revision: int
    updated_count: int
    plan_id: str | None = None
    plan_hash: str | None = None
