"""Persist sample baskets and product reference cards as metadata only."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_0015"
down_revision = "20261106_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("sample_collections"):
        op.create_table("sample_collections",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("dataset_id", sa.Integer, nullable=True),
            sa.Column("category_id", sa.Integer, nullable=True),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("items_json", sa.String, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False))
        op.create_index("ix_sample_collections_kind", "sample_collections", ["kind"])
        op.create_index("ix_sample_collections_dataset_id", "sample_collections", ["dataset_id"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified metadata backup to downgrade.")
