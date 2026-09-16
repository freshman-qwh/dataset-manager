from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


JobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
]


class JobRead(BaseModel):
    id: int
    job_type: str
    title: str
    status: JobStatus
    dataset_id: int | None
    stage: str
    progress_current: int
    progress_total: int | None
    error_count: int
    attempt: int
    parameters: dict[str, object]
    result: dict[str, object] | None
    error: dict[str, object] | None
    retry_of_id: int | None
    cancel_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobRead]
    total: int


class JobCreate(BaseModel):
    job_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    dataset_id: int | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
    progress_total: int | None = Field(default=None, ge=0)
