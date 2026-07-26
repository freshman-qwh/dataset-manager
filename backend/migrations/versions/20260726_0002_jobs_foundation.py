"""Add the persistent jobs foundation."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_0002"
down_revision: str | Sequence[str] | None = "20260726_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=120), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("retry_of_id", sa.Integer(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["retry_of_id"], ["jobs.id"]),
    )
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])
    op.create_index("ix_jobs_dataset_status", "jobs", ["dataset_id", "status"])
    op.create_index("ix_jobs_type_status", "jobs", ["job_type", "status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_type_status", table_name="jobs")
    op.drop_index("ix_jobs_dataset_status", table_name="jobs")
    op.drop_index("ix_jobs_status_created", table_name="jobs")
    op.drop_table("jobs")
