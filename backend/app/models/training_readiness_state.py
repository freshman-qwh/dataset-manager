from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.dataset import utc_now


class TrainingReadinessState(SQLModel, table=True):
    __tablename__ = "training_readiness_states"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_training_readiness_state_dataset"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    task_type: str = Field(max_length=80)
    export_format: str = Field(max_length=80)
    scope: str = Field(max_length=40)
    split: str | None = Field(default=None, max_length=40)
    include_empty: bool = Field(default=False)
    sample_query_json: str = Field(default="{}")
    class_map_json: str = Field(default="[]")
    saved_at: datetime = Field(default_factory=utc_now)
    last_export_at: datetime | None = Field(default=None)
