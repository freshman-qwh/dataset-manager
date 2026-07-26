from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    folder_path: str | None = Field(
        default=None,
        description="Folder to scan. Uses dataset.root_path when omitted.",
    )


class ScanResult(BaseModel):
    dataset_id: int
    root_path: str
    scanned: int
    imported: int
    updated: int
    unchanged: int
    missing: int
    skipped_existing: int
    skipped_unsupported: int
    hashed: int
    hash_skipped_unchanged: int
    batches_committed: int
    error_count: int
    errors: list[str] = Field(default_factory=list)
