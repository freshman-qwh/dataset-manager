from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.annotation_export import AnnotationExportSampleQuery


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


class AnomalyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_query: AnnotationExportSampleQuery = Field(default_factory=AnnotationExportSampleQuery)
    independent_capture_declared: bool = False
    include_borderline_evaluation: bool = False
    normal_ratios: list[int] = Field(default_factory=lambda: [80, 10, 10], min_length=3, max_length=3)
    abnormal_val_percent: int = Field(default=50, ge=1, le=99)
    seed: int = Field(default=42, ge=0, le=2**31-1)
    preserve_existing: bool = False
    overrides: dict[str, Literal["train", "val", "test", "exclude"]] = Field(default_factory=dict, max_length=10000)

    @model_validator(mode="after")
    def check_ratios(self):
        if sum(self.normal_ratios) != 100 or any(r < 1 or r > 98 for r in self.normal_ratios):
            raise ValueError("正常样本 train/val/test 比例需为正整数且合计 100。")
        if self.sample_query.sample_ids is not None and (not self.sample_query.sample_ids or len(self.sample_query.sample_ids) > 10000):
            raise ValueError("所选范围需为 1–10000 张图片。")
        return self
