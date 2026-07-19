from typing import Literal

from pydantic import BaseModel, Field


LabelmeImportMode = Literal["file", "directory"]
LabelmeImportStrategy = Literal["replace", "append"]
LabelmeImportSeverity = Literal["warning", "error"]


class LabelmeImportRequest(BaseModel):
    path: str = Field(min_length=1)
    mode: LabelmeImportMode = "file"
    sample_id: int | None = None
    strategy: LabelmeImportStrategy = "replace"
    dry_run: bool = False
    sync_sample_tags: bool = True


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
    checked_files: int
    matched_files: int
    imported_samples: int
    created_annotations: int
    skipped_shapes: int
    warnings: list[LabelmeImportIssue] = Field(default_factory=list)
    errors: list[LabelmeImportIssue] = Field(default_factory=list)
