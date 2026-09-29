"""Store the most recent training split confirmation for safe retries."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260929_0008"
down_revision: str | Sequence[str] | None = "20260921_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "training_split_receipts" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "training_split_receipts",
        sa.Column("dataset_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
    )


def downgrade() -> None:
    if "training_split_receipts" in inspect(op.get_bind()).get_table_names():
        op.drop_table("training_split_receipts")
