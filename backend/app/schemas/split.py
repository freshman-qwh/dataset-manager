from pydantic import BaseModel, Field


class SplitPlanRequest(BaseModel):
    train_ratio: float = Field(default=80, ge=0)
    val_ratio: float = Field(default=10, ge=0)
    test_ratio: float = Field(default=10, ge=0)
    include_test: bool = True
    stratify_by_tags: bool = True
    normal_only: bool = True
    only_unassigned: bool = False
    seed: int = 42


class SplitPlanResult(BaseModel):
    dataset_id: int
    requested: int
    updated: int
    train: int
    val: int
    test: int
    unassigned: int
    stratify_by_tags: bool
    include_test: bool
    seed: int
    warnings: list[str] = Field(default_factory=list)
