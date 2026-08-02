from typing import Literal

from pydantic import BaseModel, Field


class MetadataImportRequest(BaseModel):
    file_path: str = Field(min_length=1)
    match_by: str = Field(default="relative_path")
    tag_column: str = Field(default="tags")
    replace_tags: bool = False
    dry_run: bool = False
    expected_source_sha256: str | None = Field(
        default=None,
        pattern="^[0-9a-fA-F]{64}$",
    )


class MetadataImportIssue(BaseModel):
    severity: Literal["warning", "error"]
    code: str
    message: str
    row_number: int | None = Field(default=None, ge=1)
    match_value: str | None = None


class MetadataImportResult(BaseModel):
    dataset_id: int
    source_path: str
    source_size_bytes: int = Field(ge=0)
    source_sha256: str
    dry_run: bool
    total_rows: int
    matched: int
    planned_updates: int
    updated: int
    skipped: int
    error_count: int = Field(ge=0)
    issues: list[MetadataImportIssue] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
