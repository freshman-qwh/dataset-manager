from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.workflow import DefectSeverity, OkGrade, TriageStatus
from app.schemas.sample import SampleRead


NgGrouping = Literal["none", "defect_type", "severity", "defect_type_and_severity"]


class DefectTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=80)
    parent_id: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("code", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None


class DefectTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    parent_id: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None

    @field_validator("name", "code", mode="before")
    @classmethod
    def strip_constrained_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None


class DefectTypeRead(BaseModel):
    id: int
    dataset_id: int
    name: str
    code: str
    parent_id: int | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TriagePolicyValues(BaseModel):
    split_ok: bool = False
    ng_grouping: NgGrouping = "none"
    instructions: str = Field(default="", max_length=4000)
    clear_ok_definition: str = Field(
        default="无可见缺陷，可作为纯正常样本候选。",
        max_length=2000,
    )
    borderline_ok_definition: str = Field(
        default="存在可接受瑕疵，但按当前客户标准仍判定合格。",
        max_length=2000,
    )
    mild_definition: str = Field(default="轻微且局部。", max_length=1000)
    moderate_definition: str = Field(default="明显但未达到严重程度。", max_length=1000)
    severe_definition: str = Field(default="明显影响质量或使用。", max_length=1000)

    @field_validator("instructions", "clear_ok_definition", "borderline_ok_definition", "mild_definition", "moderate_definition", "severe_definition")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()


class TriagePolicyRead(TriagePolicyValues):
    dataset_id: int
    version: int = Field(ge=1)
    onboarding_completed: bool


class TriagePolicyPreviewRequest(TriagePolicyValues):
    expected_version: int = Field(ge=1)


class TriagePolicyUpdateRequest(TriagePolicyPreviewRequest):
    complete_onboarding: bool = True


class TriagePolicyImpactPreview(BaseModel):
    dataset_id: int
    current_version: int = Field(ge=1)
    changed: bool
    processed_count: int = Field(ge=0)
    requires_review_count: int = Field(ge=0)
    retained_detail_count: int = Field(ge=0)
    missing_ok_grade_count: int = Field(ge=0)
    missing_defect_type_count: int = Field(ge=0)
    missing_severity_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class SampleTriageWrite(BaseModel):
    expected_version: int = Field(ge=0)
    expected_file_hash: str = Field(min_length=1, max_length=128)
    triage_status: TriageStatus
    ok_grade: OkGrade | None = None
    defect_severity: DefectSeverity | None = None
    defect_type_ids: list[int] = Field(default_factory=list, max_length=100)
    primary_defect_type_id: int | None = Field(default=None, gt=0)
    triage_note: str | None = Field(default=None, max_length=4000)

    @field_validator("expected_file_hash", "triage_note")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @field_validator("defect_type_ids")
    @classmethod
    def normalize_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("defect_type_ids must contain positive integers")
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_semantics(self) -> "SampleTriageWrite":
        if self.triage_status != "ok" and self.ok_grade is not None:
            raise ValueError("Only OK samples may have an ok_grade")
        if self.ok_grade == "clear" and (
            self.defect_severity is not None or self.defect_type_ids
        ):
            raise ValueError("Clear OK samples cannot have defect types or severity")
        if self.triage_status == "untriaged" and (
            self.defect_severity is not None
            or self.defect_type_ids
            or self.primary_defect_type_id is not None
            or self.triage_note is not None
        ):
            raise ValueError("Untriaged samples cannot retain triage details")
        if (
            self.primary_defect_type_id is not None
            and self.primary_defect_type_id not in self.defect_type_ids
        ):
            raise ValueError("primary_defect_type_id must be selected in defect_type_ids")
        return self


class SampleTriageRead(BaseModel):
    sample_id: int
    dataset_id: int
    file_hash: str
    triage_status: TriageStatus
    ok_grade: OkGrade | None
    defect_severity: DefectSeverity | None
    defect_types: list[DefectTypeRead]
    primary_defect_type_id: int | None
    triage_note: str | None
    triage_version: int
    triaged_at: datetime | None
    triage_policy_version: int | None
    current_policy_version: int
    outdated: bool


BatchFieldMode = Literal["preserve", "set", "clear"]
BatchDefectTypesMode = Literal["preserve", "append", "replace", "clear"]


class BatchTriageOperation(BaseModel):
    triage_status_mode: BatchFieldMode = "preserve"
    triage_status: TriageStatus | None = None
    ok_grade_mode: BatchFieldMode = "preserve"
    ok_grade: OkGrade | None = None
    defect_severity_mode: BatchFieldMode = "preserve"
    defect_severity: DefectSeverity | None = None
    defect_types_mode: BatchDefectTypesMode = "preserve"
    defect_type_ids: list[int] = Field(default_factory=list, max_length=100)
    primary_defect_type_mode: BatchFieldMode = "preserve"
    primary_defect_type_id: int | None = Field(default=None, gt=0)
    triage_note_mode: BatchFieldMode = "preserve"
    triage_note: str | None = Field(default=None, max_length=4000)

    @field_validator("defect_type_ids")
    @classmethod
    def normalize_defect_type_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("defect_type_ids must contain positive integers")
        return sorted(set(value))

    @field_validator("triage_note")
    @classmethod
    def normalize_triage_note(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @model_validator(mode="after")
    def validate_modes(self) -> "BatchTriageOperation":
        required_values = (
            (self.triage_status_mode, self.triage_status, "设置判定时必须选择目标判定。"),
            (self.ok_grade_mode, self.ok_grade, "设置 OK 等级时必须选择目标等级。"),
            (
                self.defect_severity_mode,
                self.defect_severity,
                "设置缺陷程度时必须选择目标程度。",
            ),
            (
                self.primary_defect_type_mode,
                self.primary_defect_type_id,
                "设置主要缺陷时必须选择目标缺陷。",
            ),
            (self.triage_note_mode, self.triage_note, "设置备注时必须填写内容。"),
        )
        for mode, value, message in required_values:
            if mode == "set" and value is None:
                raise ValueError(message)
        if self.defect_types_mode in {"append", "replace"} and not self.defect_type_ids:
            raise ValueError("追加或替换缺陷类型时必须至少选择一个缺陷类型。")
        modes = (
            self.triage_status_mode,
            self.ok_grade_mode,
            self.defect_severity_mode,
            self.defect_types_mode,
            self.primary_defect_type_mode,
            self.triage_note_mode,
        )
        if all(mode == "preserve" for mode in modes):
            raise ValueError("请至少选择一项批量分拣变更。")
        return self


class BatchTriagePreviewRequest(BaseModel):
    sample_ids: list[int] = Field(min_length=1, max_length=200)
    operation: BatchTriageOperation

    @field_validator("sample_ids")
    @classmethod
    def normalize_sample_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("sample_ids must contain positive integers")
        return list(dict.fromkeys(value))


class BatchTriageExpectedSample(BaseModel):
    sample_id: int = Field(gt=0)
    expected_version: int = Field(ge=0)
    expected_file_hash: str = Field(min_length=1, max_length=128)


class BatchTriageState(BaseModel):
    triage_status: TriageStatus
    ok_grade: OkGrade | None = None
    defect_severity: DefectSeverity | None = None
    defect_type_ids: list[int] = Field(default_factory=list)
    primary_defect_type_id: int | None = None
    triage_note: str | None = None
    triage_version: int = Field(ge=0)
    outdated: bool = False


class BatchTriagePreviewItem(BaseModel):
    sample_id: int
    relative_path: str
    expected_version: int
    expected_file_hash: str
    before: BatchTriageState
    after: BatchTriageState | None = None
    changed: bool = False
    errors: list[str] = Field(default_factory=list)


class BatchTriagePreviewResponse(BaseModel):
    dataset_id: int
    dataset_revision: int
    policy_version: int
    requested: int
    changed: int
    unchanged: int
    blocked: int
    can_apply: bool
    preview_hash: str
    expected_samples: list[BatchTriageExpectedSample]
    items: list[BatchTriagePreviewItem]


class BatchTriageCommitRequest(BaseModel):
    policy_version: int = Field(ge=1)
    preview_hash: str = Field(min_length=64, max_length=64)
    expected_samples: list[BatchTriageExpectedSample] = Field(min_length=1, max_length=200)
    operation: BatchTriageOperation

    @field_validator("expected_samples")
    @classmethod
    def reject_duplicate_samples(
        cls,
        value: list[BatchTriageExpectedSample],
    ) -> list[BatchTriageExpectedSample]:
        ids = [item.sample_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("expected_samples cannot contain duplicate sample ids")
        return value


class BatchTriageCommitResponse(BaseModel):
    dataset_id: int
    dataset_revision: int
    requested: int
    updated: int
    unchanged: int


TriageQueueScope = Literal["untriaged", "pending", "current_filter", "current_split"]


class TriageNavigationResponse(BaseModel):
    current_sample: SampleRead | None = None
    previous_sample: SampleRead | None = None
    next_sample: SampleRead | None = None
    current_index: int | None = None
    total: int
    remaining: int
    queue_scope: TriageQueueScope


class TriageStats(BaseModel):
    dataset_id: int
    total_images: int
    by_status: dict[str, int]
    by_ok_grade: dict[str, int]
    by_severity: dict[str, int]
    by_defect_type: dict[str, int]
    by_export_bucket: dict[str, int]
    outdated: int
