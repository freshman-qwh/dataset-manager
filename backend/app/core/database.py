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
    "review_status": "VARCHAR(40) DEFAULT 'unlabeled'",
    "metadata_json": "TEXT",
}

TAG_COLUMNS = {
    "description": "VARCHAR(1000)",
    "parent_id": "INTEGER",
    "aliases_json": "TEXT",
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


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
