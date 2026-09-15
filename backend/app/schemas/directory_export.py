from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.job import JobRead
from app.schemas.triage import TriagePolicyRead


DirectoryExportDelivery = Literal["zip", "directory"]


class DirectoryExportSampleQuery(BaseModel):
    search: str | None = None
    file_type: Literal["image", "video", "csv"] | None = None
    file_status: str | None = None
    tag: str | None = None
    split: str | None = None
    review_status: str | None = None
    annotation_progress: str | None = None
    sample_ids: list[int] | None = Field(default=None, max_length=1000)
    triage_status: str | None = None
    ok_grade: str | None = None
    defect_severity: str | None = None
    defect_type_id: int | None = Field(default=None, gt=0)
    triage_outdated: bool | None = None
    sort_by: str = "relative_path"
    sort_order: Literal["asc", "desc"] = "asc"


class DirectoryExportPreviewRequest(BaseModel):
    delivery: DirectoryExportDelivery = "zip"
    sample_query: DirectoryExportSampleQuery = Field(
        default_factory=DirectoryExportSampleQuery
    )
    include_pending: bool = False
    include_untriaged: bool = False
    include_outdated: bool = False
    run_name: str | None = Field(default=None, max_length=80)

    @field_validator("run_name")
    @classmethod
    def normalize_run_name(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None


class DirectoryExportPreviewItem(BaseModel):
    sample_id: int
    source_relative_path: str
    target_relative_path: str | None
    bucket: str | None
    file_size: int
    triage_status: str
    outdated: bool
    included: bool
    exclusion_reason: str | None = None


class DirectoryExportPreviewResponse(BaseModel):
    dataset_id: int
    plan_id: str
    plan_hash: str
    created_at: datetime
    expires_at: datetime
    delivery: DirectoryExportDelivery
    output_name: str
    triage_policy: TriagePolicyRead
    selected_count: int
    included_count: int
    excluded_count: int
    total_bytes: int
    directory_counts: dict[str, int]
    exclusion_counts: dict[str, int]
    warnings: list[str] = Field(default_factory=list)
    blocked: bool
    page: int
    page_size: int
    page_count: int
    items: list[DirectoryExportPreviewItem]


class DirectoryExportJobCreateRequest(BaseModel):
    plan_id: str = Field(min_length=36, max_length=36)
    plan_hash: str = Field(min_length=64, max_length=64)


class DirectoryExportJobParameters(DirectoryExportJobCreateRequest):
    delivery: DirectoryExportDelivery
    output_name: str
    included_count: int = Field(ge=0)
    request_fingerprint: str


class DirectoryExportJobCreateResponse(BaseModel):
    job: JobRead
    created: bool
