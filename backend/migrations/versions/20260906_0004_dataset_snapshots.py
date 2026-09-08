"""Add immutable lightweight dataset snapshots."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260906_0004"
down_revision: str | Sequence[str] | None = "20260904_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "dataset_snapshots" in inspector.get_table_names():
        return
    op.create_table(
        "dataset_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("dataset_revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("artifact_path", sa.String(length=1000), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("annotation_count", sa.Integer(), nullable=False),
        sa.Column("class_count", sa.Integer(), nullable=False),
        sa.Column("query_json", sa.Text(), nullable=False),
        sa.Column("export_config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.UniqueConstraint("dataset_id", "artifact_path", name="uq_dataset_snapshots_artifact"),
    )
    op.create_index(
        "ix_dataset_snapshots_dataset_created",
        "dataset_snapshots",
        ["dataset_id", "created_at"],
    )
    op.create_index("ix_dataset_snapshots_dataset_id", "dataset_snapshots", ["dataset_id"])
    op.create_index(
        "ix_dataset_snapshots_dataset_revision",
        "dataset_snapshots",
        ["dataset_id", "dataset_revision"],
    )
    op.create_index(
        "ix_dataset_snapshots_content_sha256",
        "dataset_snapshots",
        ["content_sha256"],
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "dataset_snapshots" not in inspector.get_table_names():
        return
    op.drop_index("ix_dataset_snapshots_content_sha256", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_dataset_id", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_dataset_revision", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_dataset_created", table_name="dataset_snapshots")
    op.drop_table("dataset_snapshots")
