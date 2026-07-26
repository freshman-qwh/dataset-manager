"""Adopt the current Dataset Manager schema as the migration baseline."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlmodel import SQLModel

from app import models  # noqa: F401

revision: str = "20260726_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_COLUMNS: dict[str, tuple[sa.Column, ...]] = {
    "datasets": (
        sa.Column("task_type", sa.String(length=80), nullable=True, server_default="detection"),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("modality", sa.String(length=120), nullable=True),
        sa.Column("license", sa.String(length=160), nullable=True),
        sa.Column("owner", sa.String(length=160), nullable=True),
        sa.Column("project", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.String(length=4000), nullable=True),
        sa.Column("auto_scan_on_open", sa.Boolean(), nullable=True, server_default=sa.false()),
    ),
    "samples": (
        sa.Column("file_status", sa.String(length=40), nullable=True, server_default="normal"),
        sa.Column("file_modified_at", sa.DateTime(), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(), nullable=True),
        sa.Column(
            "annotation_progress",
            sa.String(length=40),
            nullable=True,
            server_default="not_started",
        ),
        sa.Column(
            "review_status",
            sa.String(length=40),
            nullable=True,
            server_default="not_reviewed",
        ),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    ),
    "tags": (
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("aliases_json", sa.Text(), nullable=True),
    ),
    "annotations": (
        sa.Column("class_id", sa.Integer(), nullable=True),
    ),
}

SQLITE_INDEXES = {
    "ix_samples_dataset_filter": (
        "samples",
        "dataset_id, file_type, file_status, annotation_progress",
    ),
    "ix_samples_dataset_split_review": (
        "samples",
        "dataset_id, split, review_status",
    ),
    "ix_samples_dataset_hash": ("samples", "dataset_id, file_hash"),
    "ix_samples_dataset_created": ("samples", "dataset_id, created_at"),
    "ix_samples_dataset_filename": ("samples", "dataset_id, filename"),
    "ix_samples_dataset_filename_lower": (
        "samples",
        "dataset_id, lower(filename), id",
    ),
    "ix_sample_tag_links_tag_sample": (
        "sample_tag_links",
        "tag_id, sample_id",
    ),
    "ix_annotations_dataset_sample": (
        "annotations",
        "dataset_id, sample_id",
    ),
    "ix_annotations_dataset_label": (
        "annotations",
        "dataset_id, label",
    ),
}


def _add_known_legacy_columns() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    for table_name, columns in LEGACY_COLUMNS.items():
        if table_name not in table_names:
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table_name, column)


def _backfill_workflow_semantics() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    required = {"datasets", "samples", "annotations", "annotation_classes"}
    if not required.issubset(tables):
        return

    bind.execute(
        text(
            "UPDATE datasets SET task_type = 'detection' "
            "WHERE task_type IS NULL OR task_type = ''"
        )
    )
    bind.execute(
        text(
            "UPDATE samples SET review_status = 'not_reviewed' "
            "WHERE review_status IS NULL OR review_status = 'unlabeled'"
        )
    )
    bind.execute(
        text(
            "UPDATE samples SET annotation_progress = 'in_progress' "
            "WHERE (annotation_progress IS NULL OR annotation_progress = 'not_started') "
            "AND EXISTS (SELECT 1 FROM annotations WHERE annotations.sample_id = samples.id)"
        )
    )
    bind.execute(
        text(
            "INSERT INTO annotation_classes (dataset_id, name, created_at, updated_at) "
            "SELECT DISTINCT annotations.dataset_id, TRIM(annotations.label), "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM annotations WHERE TRIM(annotations.label) <> '' "
            "AND NOT EXISTS ("
            "SELECT 1 FROM annotation_classes "
            "WHERE annotation_classes.dataset_id = annotations.dataset_id "
            "AND LOWER(annotation_classes.name) = LOWER(TRIM(annotations.label)))"
        )
    )
    bind.execute(
        text(
            "UPDATE annotations SET class_id = ("
            "SELECT annotation_classes.id FROM annotation_classes "
            "WHERE annotation_classes.dataset_id = annotations.dataset_id "
            "AND LOWER(annotation_classes.name) = LOWER(TRIM(annotations.label)) LIMIT 1) "
            "WHERE class_id IS NULL"
        )
    )


def _ensure_indexes() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for index_name, (table_name, columns) in SQLITE_INDEXES.items():
        if table_name not in tables:
            continue
        bind.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON {table_name} ({columns})"
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)
    _add_known_legacy_columns()
    _backfill_workflow_semantics()
    _ensure_indexes()


def downgrade() -> None:
    raise RuntimeError(
        "The baseline migration cannot be downgraded destructively. "
        "Restore the verified pre-migration backup instead."
    )
