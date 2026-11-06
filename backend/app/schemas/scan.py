from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.job import JobRead


class ScanRequest(BaseModel):
    folder_path: str | None = Field(
        default=None,
        description="Folder to scan. Uses dataset.root_path when omitted.",
    )
    batch_id: int | None = Field(default=None, gt=0)
    new_batch_name: str | None = Field(default=None, min_length=1, max_length=160)
    import_format: Literal["auto", "folder", "mvtec_ad", "visa"] = "auto"
    recognize_existing: bool = False

    @model_validator(mode="after")
    def validate_batch_choice(self):
        if self.new_batch_name is not None:
            self.new_batch_name = self.new_batch_name.strip()
            if not self.new_batch_name:
                raise ValueError("请填写批次名称。")
        if self.batch_id is not None and self.new_batch_name is not None:
            raise ValueError("请选择已有批次或新建批次，不能同时指定。")
        return self


class ImportPreview(BaseModel):
    detected_format: str
    categories: list[str] = Field(default_factory=list)
    image_count: int
    mask_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    official_split_counts: dict[str, int] = Field(default_factory=dict)


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
    detected_format: str = "folder"
    assigned_batch_id: int | None = None
    benchmark_images: int = 0
    linked_masks: int = 0
    import_warnings: list[str] = Field(default_factory=list)


class ScanJobCreateResponse(BaseModel):
    job: JobRead
    created: bool
