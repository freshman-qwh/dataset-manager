"""Dataset-local reception recipes and explicit metadata previews."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.industrial import FilenameGroupRule
from app.schemas.validation import NormalizedRoi


class CategoryReceptionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directory: str = Field(min_length=1, max_length=2000)
    category_id: int = Field(gt=0)

    @field_validator("directory")
    @classmethod
    def normalize_directory(cls, value: str) -> str:
        value = value.strip().replace("\\", "/")
        if not value or "\0" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
            raise ValueError("类别目录必须是相对于扫描目录的路径；根目录可填写 .。")
        if value == ".":
            return value
        parts = [part for part in value.rstrip("/").split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("类别目录不能包含 . 或 .. 路径段。")
        return "/".join(parts)


class BatchReceptionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="默认接收方案", min_length=1, max_length=160)
    import_format: Literal["auto", "folder", "mvtec_ad", "visa"] = "auto"
    filename_rule: FilenameGroupRule | None = None
    category_rules: list[CategoryReceptionRule] = Field(default_factory=list, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("方案名称不能为空。")
        return value.strip()

    @model_validator(mode="after")
    def unique_directories(self):
        directories = [rule.directory for rule in self.category_rules]
        if len(directories) != len(set(directories)):
            raise ValueError("类别目录规则不能重复。")
        return self


class BatchReceptionContext(BaseModel):
    policy_version: int
    split_ok: bool
    ng_grouping: str
    roi: NormalizedRoi | None = None


class BatchReceptionProfileRead(BaseModel):
    saved: bool
    dataset_revision: int
    profile: BatchReceptionProfile
    context: BatchReceptionContext


class BatchReceptionProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    profile: BatchReceptionProfile


class BatchReceptionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: int = Field(gt=0)
    expected_revision: int = Field(ge=1)
