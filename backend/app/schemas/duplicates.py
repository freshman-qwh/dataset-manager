from pydantic import BaseModel, Field


class DuplicateSample(BaseModel):
    id: int
    filename: str
    relative_path: str
    file_size: int
    file_status: str
    split: str | None
    annotation_progress: str
    review_status: str


class DuplicateGroup(BaseModel):
    file_hash: str
    count: int
    cross_split: bool
    training_splits: list[str] = Field(default_factory=list)
    split_counts: dict[str, int] = Field(default_factory=dict)
    samples_truncated: bool
    samples: list[DuplicateSample]


class DuplicateReport(BaseModel):
    dataset_id: int
    group_count: int
    duplicate_sample_count: int
    cross_split_group_count: int
    cross_split_sample_count: int
    filtered_group_count: int
    leakage_only: bool
    page: int
    page_size: int
    has_previous: bool
    has_next: bool
    groups: list[DuplicateGroup]
