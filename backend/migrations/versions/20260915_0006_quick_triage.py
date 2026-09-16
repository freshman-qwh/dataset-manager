"""Add quick triage metadata and defect taxonomy."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260915_0006"
down_revision: str | Sequence[str] | None = "20260907_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DATASET_COLUMNS = (
    sa.Column(
        "triage_policy_version",
        sa.Integer(),
        nullable=False,
        server_default="1",
    ),
    sa.Column("triage_policy_json", sa.Text(), nullable=True),
)

SAMPLE_COLUMNS = (
    sa.Column(
        "triage_status",
        sa.String(length=40),
        nullable=False,
        server_default="untriaged",
    ),
    sa.Column("ok_grade", sa.String(length=40), nullable=True),
    sa.Column("defect_severity", sa.String(length=40), nullable=True),
    sa.Column("primary_defect_type_id", sa.Integer(), nullable=True),
    sa.Column("triage_note", sa.String(length=4000), nullable=True),
    sa.Column(
        "triage_version",
        sa.Integer(),
        nullable=False,
        server_default="0",
    ),
    sa.Column("triaged_at", sa.DateTime(), nullable=True),
    sa.Column("triage_policy_version", sa.Integer(), nullable=True),
    sa.Column("triaged_file_hash", sa.String(length=128), nullable=True),
)


def _add_missing_columns(table_name: str, columns: tuple[sa.Column, ...]) -> None:
    inspector = inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def _create_index_if_missing(
    table_name: str,
    index_name: str,
    columns: list[str],
) -> None:
    inspector = inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    _add_missing_columns("datasets", DATASET_COLUMNS)
    _add_missing_columns("samples", SAMPLE_COLUMNS)

    if "defect_types" not in tables:
        op.create_table(
            "defect_types",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
            sa.ForeignKeyConstraint(["parent_id"], ["defect_types.id"]),
            sa.UniqueConstraint(
                "dataset_id",
                "code",
                name="uq_defect_types_dataset_code",
            ),
        )
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "sample_defect_links" not in tables:
        op.create_table(
            "sample_defect_links",
            sa.Column("sample_id", sa.Integer(), nullable=False),
            sa.Column("defect_type_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["sample_id"], ["samples.id"]),
            sa.ForeignKeyConstraint(["defect_type_id"], ["defect_types.id"]),
            sa.PrimaryKeyConstraint("sample_id", "defect_type_id"),
        )

    _create_index_if_missing(
        "samples",
        "ix_samples_dataset_triage",
        ["dataset_id", "triage_status", "ok_grade", "defect_severity"],
    )
    _create_index_if_missing(
        "samples",
        "ix_samples_primary_defect_type_id",
        ["primary_defect_type_id"],
    )
    _create_index_if_missing(
        "defect_types",
        "ix_defect_types_dataset_id",
        ["dataset_id"],
    )
    _create_index_if_missing(
        "defect_types",
        "ix_defect_types_parent_id",
        ["parent_id"],
    )
    _create_index_if_missing(
        "defect_types",
        "ix_defect_types_is_active",
        ["is_active"],
    )
    _create_index_if_missing(
        "defect_types",
        "ix_defect_types_dataset_parent",
        ["dataset_id", "parent_id", "is_active"],
    )
    _create_index_if_missing(
        "sample_defect_links",
        "ix_sample_defect_links_type_sample",
        ["defect_type_id", "sample_id"],
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "sample_defect_links" in tables:
        op.drop_table("sample_defect_links")
    if "defect_types" in tables:
        op.drop_table("defect_types")

    sample_columns = {column["name"] for column in inspector.get_columns("samples")}
    for name in reversed([column.name for column in SAMPLE_COLUMNS]):
        if name in sample_columns:
            op.drop_column("samples", name)
    dataset_columns = {column["name"] for column in inspector.get_columns("datasets")}
    for name in reversed([column.name for column in DATASET_COLUMNS]):
        if name in dataset_columns:
            op.drop_column("datasets", name)
