from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.sample import SampleRead

CollectionKind = Literal["basket", "reference"]
ReferenceVerdict = Literal["acceptable", "unacceptable", "uncertain"]


class CollectionItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: int = Field(gt=0)
    file_hash: str | None = Field(default=None, max_length=128)
    verdict: ReferenceVerdict | None = None
    note: str = Field(default="", max_length=500)


class SampleCollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    kind: CollectionKind = "basket"
    dataset_id: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    items: list[CollectionItemInput] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("集合名称不能为空。")
        return value

    @model_validator(mode="after")
    def valid_scope(self):
        if self.kind == "reference" and self.dataset_id is None:
            raise ValueError("参考卡必须属于一个数据集。")
        if self.category_id is not None and self.dataset_id is None:
            raise ValueError("选择类别前请指定数据集。")
        if self.kind == "basket" and (self.dataset_id is not None or self.category_id is not None):
            raise ValueError("收集篮跨数据集管理，请勿限定类别或数据集。")
        return self


class SampleCollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    items: list[CollectionItemInput] | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("集合名称不能为空。")
        return value


class CollectionItemRead(BaseModel):
    sample_id: int
    file_hash: str
    dataset_id: int
    filename: str
    relative_path: str
    verdict: ReferenceVerdict | None
    note: str
    sample: SampleRead | None
    unavailable_reason: str | None


class SampleCollectionRead(BaseModel):
    id: int
    name: str
    kind: CollectionKind
    dataset_id: int | None
    category_id: int | None
    version: int
    items: list[CollectionItemRead]
    created_at: datetime
    updated_at: datetime
