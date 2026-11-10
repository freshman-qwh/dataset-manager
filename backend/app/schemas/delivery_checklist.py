"""Goal-specific explanations of the existing frozen industrial plan."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.industrial import AnomalyPreviewRequest, FrozenPlanRead
from app.schemas.validation import NormalizedRoi


DeliveryTarget = Literal["training_package", "evaluation", "exploration"]
ChecklistAction = Literal["triage", "groups", "scope", "collect", "review"]


class DeliveryChecklistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: DeliveryTarget = "training_package"
    protocol: AnomalyPreviewRequest = Field(default_factory=AnomalyPreviewRequest)
    model: Literal["padim", "patchcore"] = "padim"
    image_size: Literal[128, 256, 384] = 256
    roi: NormalizedRoi | None = None


class ChecklistSample(BaseModel):
    id: int
    relative_path: str


class ChecklistIssue(BaseModel):
    key: str
    title: str
    severity: Literal["blocker", "excluded", "notice"]
    count: int = Field(ge=0)
    sample_ids: list[int] = Field(default_factory=list, max_length=10000)
    samples: list[ChecklistSample] = Field(default_factory=list, max_length=6)
    action: ChecklistAction
    guidance: str


class ChecklistCoverageRow(BaseModel):
    id: int | None
    name: str
    total: int = Field(ge=0)
    normal: int = Field(ge=0)
    abnormal: int = Field(ge=0)
    pending: int = Field(ge=0)
    normal_groups: int = Field(ge=0)
    abnormal_groups: int = Field(ge=0)


class ChecklistDefectCoverage(BaseModel):
    id: int
    name: str
    total: int = Field(ge=0)
    groups: int = Field(ge=0)


class ChecklistCoverage(BaseModel):
    categories: list[ChecklistCoverageRow] = Field(default_factory=list)
    batches: list[ChecklistCoverageRow] = Field(default_factory=list)
    defects: list[ChecklistDefectCoverage] = Field(default_factory=list)


class DeliveryChecklistRead(BaseModel):
    target: DeliveryTarget
    dataset_revision: int
    ready: bool
    plan: FrozenPlanRead
    issues: list[ChecklistIssue]
    coverage: ChecklistCoverage
    notes: list[str]
