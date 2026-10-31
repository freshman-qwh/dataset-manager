from datetime import datetime

from sqlmodel import Field, SQLModel
from app.models.dataset import utc_now


class ValidationRun(SQLModel, table=True):
    __tablename__ = "validation_runs"
    id: str = Field(primary_key=True, max_length=32)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    dataset_revision: int
    plan_id: str = Field(max_length=32)
    plan_hash: str = Field(max_length=64)
    mode: str = Field(max_length=40)
    name: str = Field(max_length=160)
    recipe_json: str
    contract_sha256: str = Field(max_length=64)
    summary_json: str | None = None
    parent_run_id: str | None = Field(default=None, max_length=32)
    job_id: int | None = Field(default=None, foreign_key="jobs.id")
    created_at: datetime = Field(default_factory=utc_now)


class ValidationDecision(SQLModel, table=True):
    __tablename__ = "validation_decisions"
    run_id: str = Field(primary_key=True, foreign_key="validation_runs.id")
    threshold: float
    report_json: str
    created_at: datetime = Field(default_factory=utc_now)


class ValidationTestExposure(SQLModel, table=True):
    __tablename__ = "validation_test_exposures"
    sha256: str = Field(primary_key=True, max_length=64)
    # Retain test exposure even after explicit deletion of a run's artifacts.
    first_run_id: str = Field(max_length=32)
    created_at: datetime = Field(default_factory=utc_now)


class ValidationReview(SQLModel, table=True):
    __tablename__ = "validation_reviews"
    run_id: str = Field(primary_key=True, foreign_key="validation_runs.id")
    sample_id: int = Field(primary_key=True, foreign_key="samples.id")
    sha256: str = Field(max_length=64)
    state: str = Field(default="pending", max_length=32)
    updated_at: datetime = Field(default_factory=utc_now)
