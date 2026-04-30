from pydantic import BaseModel

from app.schemas.sample import SampleRead


class DuplicateGroup(BaseModel):
    file_hash: str
    count: int
    samples: list[SampleRead]


class DuplicateReport(BaseModel):
    dataset_id: int
    group_count: int
    duplicate_sample_count: int
    groups: list[DuplicateGroup]
