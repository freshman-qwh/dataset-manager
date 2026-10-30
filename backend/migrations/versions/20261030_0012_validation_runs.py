"""Durable local validation runs, frozen decisions and review provenance."""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0012"
down_revision = "20261030_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models.validation import ValidationRun, ValidationDecision, ValidationTestExposure, ValidationReview
    for model in (ValidationRun, ValidationDecision, ValidationTestExposure, ValidationReview):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("Restore a verified metadata backup to downgrade.")
