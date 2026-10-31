"""Keep test-content exposure history after deleting an experiment."""
from alembic import op
import sqlalchemy as sa

revision = "20261101_0013"
down_revision = "20261030_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    keys = sa.inspect(op.get_bind()).get_foreign_keys("validation_test_exposures")
    for key in keys:
        if key["constrained_columns"] == ["first_run_id"]:
            convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
            with op.batch_alter_table("validation_test_exposures", naming_convention=convention) as batch:
                batch.drop_constraint(key["name"] or "fk_validation_test_exposures_first_run_id_validation_runs", type_="foreignkey")


def downgrade() -> None:
    raise RuntimeError("Restore a verified metadata backup to downgrade.")
