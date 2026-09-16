"""Add reusable dataset saved views."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260907_0005"
down_revision: str | Sequence[str] | None = "20260906_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "dataset_saved_views" in inspector.get_table_names():
        return
    op.create_table(
        "dataset_saved_views",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("queue_scope", sa.String(length=40), nullable=False),
        sa.Column("query_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.UniqueConstraint("dataset_id", "name", name="uq_dataset_saved_views_name"),
    )
    op.create_index(
        "ix_dataset_saved_views_dataset_updated",
        "dataset_saved_views",
        ["dataset_id", "updated_at"],
    )
    op.create_index(
        "ix_dataset_saved_views_dataset_id",
        "dataset_saved_views",
        ["dataset_id"],
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "dataset_saved_views" not in inspector.get_table_names():
        return
    op.drop_index("ix_dataset_saved_views_dataset_id", table_name="dataset_saved_views")
    op.drop_index("ix_dataset_saved_views_dataset_updated", table_name="dataset_saved_views")
    op.drop_table("dataset_saved_views")
