"""Capture identity and durable industrial confirmation receipts."""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0010"
down_revision = "20261030_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("samples")}
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("samples")}
    for name in ("capture_group_id", "capture_batch_id"):
        if name not in columns:
            op.add_column("samples", sa.Column(name, sa.String(160), nullable=True))
        if f"ix_samples_{name}" not in indexes:
            op.create_index(f"ix_samples_{name}", "samples", [name])
    if not sa.inspect(bind).has_table("industrial_receipts"):
        op.create_table("industrial_receipts",
            sa.Column("plan_id", sa.String(32), primary_key=True),
            sa.Column("dataset_id", sa.Integer, sa.ForeignKey("datasets.id"), nullable=False),
            sa.Column("plan_hash", sa.String(64), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("result_json", sa.String, nullable=False))
        op.create_index("ix_industrial_receipts_dataset_id", "industrial_receipts", ["dataset_id"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified metadata backup to downgrade.")
