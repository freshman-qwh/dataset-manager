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
    skipped_existing: int
    skipped_unsupported: int
    errors: list[str] = []
