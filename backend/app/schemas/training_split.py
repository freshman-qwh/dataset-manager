from typing import Literal

from pydantic import BaseModel, Field


TrainingSplit = Literal["train", "val", "test"]
TriageFilter = Literal["all", "ok", "ng"]


class TrainingSplitRequest(BaseModel):
    train_ratio: float = Field(default=80, ge=0)
    val_ratio: float = Field(default=10, ge=0)
    test_ratio: float = Field(default=10, ge=0)
    include_test: bool = True
    include_empty: bool = True
    triage_filter: TriageFilter = "all"
    seed: int = 42
    overrides: dict[int, TrainingSplit | None] = Field(default_factory=dict)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class TrainingSplitRow(BaseModel):
    sample_id: int
    relative_path: str
    annotation_progress: str
    triage_status: str
    current_split: str | None
    suggested_split: TrainingSplit | None
    duplicate_count: int
    warning: str | None = None


class TrainingSplitPreview(BaseModel):
    dataset_id: int
    fingerprint: str
    candidate_count: int
    unassigned_count: int
    duplicate_group_count: int
    excluded_counts: dict[str, int]
    change_count: int
    split_counts: dict[str, int]
    blocked: bool
    warnings: list[str]
    page: int
    page_count: int
    rows: list[TrainingSplitRow]


class TrainingSplitCommitRequest(TrainingSplitRequest):
    fingerprint: str


class TrainingSplitCommitResult(BaseModel):
    updated: int
    sample_ids: list[int]
    split_counts: dict[str, int]
    dataset_revision: int
