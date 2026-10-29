"""Keep industrial preparation separate from geometry task capabilities."""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0009"
down_revision = "20260929_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("datasets")}
    if "workflow_profile" not in columns:
        op.add_column("datasets", sa.Column("workflow_profile", sa.String(40), nullable=False, server_default="general"))


def downgrade() -> None:
    raise RuntimeError("Restore a verified metadata backup to downgrade.")
