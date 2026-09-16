from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.workflow import DefectSeverity, OkGrade
from app.schemas.job import JobRead
from app.schemas.triage import DefectTypeRead, TriagePolicyRead


DirectoryMappingStatus = Literal["ok", "ng", "pending"]
DirectoryMappingExistingBehavior = Literal["skip", "overwrite"]
DirectoryMappingDecision = Literal[
    "apply",
    "unchanged",
    "skipped_existing",
    "unmapped",
    "file_unavailable",
]


class TriageDirectorySource(BaseModel):
    directory: str
    image_count: int = Field(ge=0)
    untriaged_count: int = Field(ge=0)
    existing_count: int = Field(ge=0)
    status_counts: dict[str, int]
    examples: list[str]


class TriageDirectorySourceResponse(BaseModel):
    dataset_id: int
    dataset_revision: int = Field(ge=1)
    triage_policy: TriagePolicyRead
    defect_types: list[DefectTypeRead]
    total_directories: int = Field(ge=0)
    total_images: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    page_count: int = Field(ge=1)
    items: list[TriageDirectorySource]


class TriageDirectoryMappingRule(BaseModel):
    source_directory: str = Field(max_length=2000)
    triage_status: DirectoryMappingStatus
    ok_grade: OkGrade | None = None
    defect_severity: DefectSeverity | None = None
    defect_type_id: int | None = Field(default=None, gt=0)

    @field_validator("source_directory")
    @classmethod
    def normalize_directory(cls, value: str) -> str:
        return value.strip().replace("\\", "/").strip("/")

    @model_validator(mode="after")
    def validate_target_shape(self) -> "TriageDirectoryMappingRule":
        if self.triage_status != "ok" and self.ok_grade is not None:
            raise ValueError("只有 OK 目录可以设置 OK 等级。")
        if self.triage_status != "ng" and (
            self.defect_severity is not None or self.defect_type_id is not None
        ):
            raise ValueError("只有 NG 目录可以设置缺陷类型或程度。")
        return self


class TriageDirectoryMappingPreviewRequest(BaseModel):
    mappings: list[TriageDirectoryMappingRule] = Field(min_length=1, max_length=1000)
    existing_behavior: DirectoryMappingExistingBehavior = "skip"

    @model_validator(mode="after")
    def validate_unique_directories(self) -> "TriageDirectoryMappingPreviewRequest":
        directories = [item.source_directory.casefold() for item in self.mappings]
        if len(directories) != len(set(directories)):
            raise ValueError("同一个来源目录只能配置一次映射。")
        return self


class TriageDirectoryMappingPreviewItem(BaseModel):
    sample_id: int
    relative_path: str
    source_directory: str
    current_status: str
    target_status: DirectoryMappingStatus | None
    target_ok_grade: OkGrade | None = None
    target_defect_severity: DefectSeverity | None = None
    target_defect_type_id: int | None = None
    decision: DirectoryMappingDecision


class TriageDirectoryMappingPreviewResponse(BaseModel):
    dataset_id: int
    plan_id: str
    plan_hash: str
    created_at: datetime
    expires_at: datetime
    existing_behavior: DirectoryMappingExistingBehavior
    total_images: int = Field(ge=0)
    mapped_sample_count: int = Field(ge=0)
    change_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    skipped_existing_count: int = Field(ge=0)
    unmapped_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    blocked: bool
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    page_count: int = Field(ge=1)
    items: list[TriageDirectoryMappingPreviewItem]


class TriageDirectoryMappingJobCreateRequest(BaseModel):
    plan_id: str = Field(min_length=36, max_length=36)
    plan_hash: str = Field(min_length=64, max_length=64)


class TriageDirectoryMappingJobParameters(TriageDirectoryMappingJobCreateRequest):
    change_count: int = Field(ge=0)
    request_fingerprint: str


class TriageDirectoryMappingJobCreateResponse(BaseModel):
    job: JobRead
    created: bool
