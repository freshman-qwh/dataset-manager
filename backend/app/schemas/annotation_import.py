from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.job import JobRead


LabelmeImportMode = Literal["file", "directory"]
LabelmeImportStrategy = Literal["replace", "append"]
LabelmeImportSeverity = Literal["warning", "error"]


class LabelmeImportRequest(BaseModel):
    path: str = Field(min_length=1)
    mode: LabelmeImportMode = "file"
    sample_id: int | None = None
    strategy: LabelmeImportStrategy = "replace"
    dry_run: bool = False
    sync_sample_tags: bool = False
    expected_source_sha256: str | None = Field(
        default=None,
        pattern="^[0-9a-fA-F]{64}$",
    )
    expected_plan_fingerprint: str | None = Field(
        default=None,
        pattern="^[0-9a-fA-F]{64}$",
    )


class LabelmeImportIssue(BaseModel):
    severity: LabelmeImportSeverity
    code: str
    message: str
    file_path: str | None = None
    sample_id: int | None = None
    sample_path: str | None = None


class LabelmeImportResult(BaseModel):
    dataset_id: int
    source_path: str
    mode: LabelmeImportMode
    strategy: LabelmeImportStrategy
    dry_run: bool
    source_size_bytes: int = Field(ge=0)
    source_sha256: str
    plan_fingerprint: str
    checked_files: int
    matched_files: int
    imported_samples: int
    created_annotations: int
    skipped_shapes: int
    warnings: list[LabelmeImportIssue] = Field(default_factory=list)
    errors: list[LabelmeImportIssue] = Field(default_factory=list)


class LabelmeImportJobCreateRequest(BaseModel):
    path: str = Field(min_length=1)
    mode: LabelmeImportMode = "file"
    sample_id: int | None = None
    strategy: LabelmeImportStrategy = "replace"
    sync_sample_tags: bool = False
    expected_source_sha256: str = Field(pattern="^[0-9a-fA-F]{64}$")
    expected_plan_fingerprint: str = Field(pattern="^[0-9a-fA-F]{64}$")


class LabelmeImportJobParameters(LabelmeImportJobCreateRequest):
    source_size_bytes: int = Field(ge=0)
    checked_files: int = Field(ge=0)
    planned_samples: int = Field(ge=0)
    planned_annotations: int = Field(ge=0)
    preview_error_count: int = Field(ge=0)
    request_fingerprint: str = Field(pattern="^[0-9a-fA-F]{64}$")


class LabelmeImportJobCreateResponse(BaseModel):
    job: JobRead
    created: bool


class LabelmeImportRollbackJobCreateResponse(BaseModel):
    job: JobRead
    created: bool
