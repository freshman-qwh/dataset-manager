from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.industrial import AnomalyPreviewRequest
from app.schemas.annotation_export import AnnotationExportSampleQuery
from app.schemas.job import JobRead


class NormalizedRoi(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def within_image(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("ROI 必须在图片范围内。")
        return self


class ValidationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["evaluation", "exploration"] = "evaluation"
    protocol: AnomalyPreviewRequest = Field(default_factory=AnomalyPreviewRequest)
    model: Literal["padim", "patchcore"] = "padim"
    image_size: Literal[128, 256, 384] = 256
    roi: NormalizedRoi | None = None


class ValidationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(default="基线验证", min_length=1, max_length=160)


class ValidationRunRead(BaseModel):
    id: str
    dataset_id: int
    dataset_revision: int
    name: str
    mode: str
    recipe: dict[str, object]
    parent_run_id: str | None
    job: JobRead | None
    created_at: datetime
    current_dataset_revision: int
    summary: dict[str, object] | None = None


class RuntimeConfigure(BaseModel):
    python_path: str = Field(min_length=1, max_length=2000)


class RuntimeInstall(BaseModel):
    base_python: str | None = Field(default=None, max_length=2000)


class RuntimeRead(BaseModel):
    ready: bool
    python_path: str | None = None
    message: str
    versions: dict[str, str] = Field(default_factory=dict)
    base_python: str | None = None
    install_job: JobRead | None = None


class ThresholdRequest(BaseModel):
    threshold: float = Field(allow_inf_nan=False)


class ReviewRequest(BaseModel):
    sample_ids: list[int] = Field(min_length=1, max_length=200)


class ReviewUpdate(BaseModel):
    state: Literal["pending", "reviewed", "ignored"]
    expected_version: int | None = Field(default=None, ge=0)
    expected_file_hash: str | None = None


class BatchPreviewRequest(BaseModel):
    target_dataset_id: int = Field(gt=0)
    sample_ids: list[int] | None = Field(default=None, min_length=1, max_length=2000)
    independent_capture_declared: bool = False


class RoiSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roi: NormalizedRoi | None = None
    expected_dataset_revision: int = Field(ge=1)


class QualityInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sample_query: AnnotationExportSampleQuery = Field(default_factory=AnnotationExportSampleQuery)
    roi: NormalizedRoi | None = None
    dark_below: float = Field(default=35, ge=0, le=120)
    bright_above: float = Field(default=220, ge=135, le=255)
    sharpness_below: float = Field(default=30, ge=0, le=10000)
    similar_distance: int = Field(default=4, ge=0, le=12)
