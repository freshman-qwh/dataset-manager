from collections.abc import Generator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

DATASET_COLUMNS = {
    "task_type": "VARCHAR(80) DEFAULT 'detection'",
    "source": "VARCHAR(500)",
    "modality": "VARCHAR(120)",
    "license": "VARCHAR(160)",
    "owner": "VARCHAR(160)",
    "project": "VARCHAR(160)",
    "notes": "VARCHAR(4000)",
    "auto_scan_on_open": "BOOLEAN DEFAULT 0",
}

SAMPLE_COLUMNS = {
    "file_status": "VARCHAR(40) DEFAULT 'normal'",
    "file_modified_at": "DATETIME",
    "last_scanned_at": "DATETIME",
    "annotation_progress": "VARCHAR(40) DEFAULT 'not_started'",
    "review_status": "VARCHAR(40) DEFAULT 'not_reviewed'",
    "metadata_json": "TEXT",
}

TAG_COLUMNS = {
    "description": "VARCHAR(1000)",
    "parent_id": "INTEGER",
    "aliases_json": "TEXT",
}

ANNOTATION_COLUMNS = {
    "class_id": "INTEGER",
}


def _ensure_columns(table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns(table_name)}
    with engine.begin() as connection:
        for column_name, column_type in columns.items():
            if column_name not in existing:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _backfill_workflow_semantics() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"datasets", "samples", "annotations", "annotation_classes"}.issubset(tables):
        return
    with engine.begin() as connection:
        connection.execute(text("UPDATE datasets SET task_type = 'detection' WHERE task_type IS NULL OR task_type = ''"))
        connection.execute(
            text("UPDATE samples SET review_status = 'not_reviewed' WHERE review_status IS NULL OR review_status = 'unlabeled'")
        )
        connection.execute(
            text(
                "UPDATE samples SET annotation_progress = 'in_progress' "
                "WHERE (annotation_progress IS NULL OR annotation_progress = 'not_started') "
                "AND EXISTS (SELECT 1 FROM annotations WHERE annotations.sample_id = samples.id)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO annotation_classes (dataset_id, name, created_at, updated_at) "
                "SELECT DISTINCT annotations.dataset_id, TRIM(annotations.label), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "FROM annotations WHERE TRIM(annotations.label) <> '' "
                "AND NOT EXISTS ("
                "SELECT 1 FROM annotation_classes "
                "WHERE annotation_classes.dataset_id = annotations.dataset_id "
                "AND LOWER(annotation_classes.name) = LOWER(TRIM(annotations.label)))"
            )
        )
        connection.execute(
            text(
                "UPDATE annotations SET class_id = ("
                "SELECT annotation_classes.id FROM annotation_classes "
                "WHERE annotation_classes.dataset_id = annotations.dataset_id "
                "AND LOWER(annotation_classes.name) = LOWER(TRIM(annotations.label)) LIMIT 1) "
                "WHERE class_id IS NULL"
            )
        )


def init_db() -> None:
    """Create local directories and SQLite tables for the MVP."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.storage_root.mkdir(parents=True, exist_ok=True)

    # Import models before create_all so SQLModel metadata is complete.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _ensure_columns("datasets", DATASET_COLUMNS)
    _ensure_columns("samples", SAMPLE_COLUMNS)
    _ensure_columns("tags", TAG_COLUMNS)
    _ensure_columns("annotations", ANNOTATION_COLUMNS)
    _backfill_workflow_semantics()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
