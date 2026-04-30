from pydantic import BaseModel, Field


class MetadataImportRequest(BaseModel):
    file_path: str = Field(min_length=1)
    match_by: str = Field(default="relative_path")
    tag_column: str = Field(default="tags")
    replace_tags: bool = False


class MetadataImportResult(BaseModel):
    dataset_id: int
    source_path: str
    total_rows: int
    matched: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
