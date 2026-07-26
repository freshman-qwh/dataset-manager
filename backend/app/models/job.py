from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_dataset_status", "dataset_id", "status"),
        Index("ix_jobs_type_status", "job_type", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    job_type: str = Field(max_length=80)
    title: str = Field(max_length=200)
    status: str = Field(default="queued", max_length=40)
    dataset_id: int | None = Field(default=None, foreign_key="datasets.id")
    stage: str = Field(default="queued", max_length=120)
    progress_current: int = Field(default=0, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    error_count: int = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)
    parameters_json: str = Field(default="{}")
    result_json: str | None = Field(default=None)
    error_json: str | None = Field(default=None)
    retry_of_id: int | None = Field(default=None, foreign_key="jobs.id")
    cancel_requested_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now)
