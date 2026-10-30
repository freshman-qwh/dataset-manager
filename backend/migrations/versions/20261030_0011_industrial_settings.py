"""Reusable industrial preparation preferences."""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0011"
down_revision = "20261030_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("datasets")}
    if "industrial_settings_json" not in columns:
        op.add_column("datasets", sa.Column("industrial_settings_json", sa.String, nullable=True))


def downgrade() -> None:
    raise RuntimeError("Restore a verified metadata backup to downgrade.")
