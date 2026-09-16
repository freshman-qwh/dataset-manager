from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from app.core import migrations
from app.core.config import get_settings
from app.schemas.database_backup import DatabaseBackupJobCreateResponse
from app.schemas.job import JobCreate
from app.services import job_artifact_service, job_service
from app.services.job_runner import JobContext


DATABASE_BACKUP_JOB_TYPE = "database.backup"
BACKUP_CONTRACT_VERSION = 1
BACKUP_MEDIA_TYPE = "application/vnd.sqlite3"
BACKUP_PAGE_BATCH = 256
BACKUP_TABLES = (
    "datasets",
    "samples",
    "tags",
    "sample_tag_links",
    "annotation_classes",
    "annotations",
    "training_readiness_states",
    "jobs",
)


def create_database_backup_job(session: Session) -> DatabaseBackupJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    database_path = get_settings().database_path.resolve()
    if not database_path.is_file():
        raise job_service.JobStateError("The SQLite database file does not exist.")

    parameters: dict[str, object] = {
        "contract_version": BACKUP_CONTRACT_VERSION,
        "source_database_name": database_path.name,
        "expected_revision": migrations.current_revision(database_path),
        "raw_files_included": False,
    }

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=DATABASE_BACKUP_JOB_TYPE,
        dataset_id=None,
    )
    if active is not None:
        session.commit()
        return DatabaseBackupJobCreateResponse(job=active, created=False)

    created = job_service.create_job(
        session,
        JobCreate(
            job_type=DATABASE_BACKUP_JOB_TYPE,
            title="备份 SQLite 元数据",
            parameters=parameters,
        ),
    )
    return DatabaseBackupJobCreateResponse(job=created, created=True)


def _read_page_count(database_path: Path) -> int:
    with closing(_open_read_only(database_path)) as connection:
        row = connection.execute("PRAGMA page_count").fetchone()
    return max(int(row[0]) if row else 0, 1)


def _open_read_only(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        f"file:{database_path.resolve().as_posix()}?mode=ro",
        uri=True,
        timeout=5,
    )


def _copy_database(
    source_path: Path,
    target_path: Path,
    *,
    context: JobContext,
) -> int:
    page_count = _read_page_count(source_path)
    context.report_progress(
        current=0,
        total=page_count,
        stage="copying_database",
    )

    def checkpoint_copy(
        _status: int,
        _remaining: int,
        _total: int,
    ) -> None:
        # Updating the source job row during every backup step can make SQLite
        # restart copied pages. A read-only cancellation checkpoint keeps the
        # snapshot cooperative without turning progress reporting into a writer.
        context.checkpoint()

    with closing(_open_read_only(source_path)) as source_connection:
        with closing(sqlite3.connect(target_path)) as target_connection:
            source_connection.backup(
                target_connection,
                pages=BACKUP_PAGE_BATCH,
                progress=checkpoint_copy,
                sleep=0.05,
            )
    return page_count


def _inspect_backup(database_path: Path) -> dict[str, object]:
    with closing(_open_read_only(database_path)) as connection:
        quick_check_row = connection.execute("PRAGMA quick_check").fetchone()
        quick_check = str(quick_check_row[0]) if quick_check_row else "missing result"
        if quick_check.lower() != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {quick_check}")

        foreign_key_violation_count = sum(
            1 for _row in connection.execute("PRAGMA foreign_key_check")
        )
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        table_counts = {
            table_name: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            )
            for table_name in BACKUP_TABLES
            if table_name in table_names
        }

    return {
        "quick_check": quick_check,
        "foreign_key_violation_count": foreign_key_violation_count,
        "current_revision": migrations.current_revision(database_path),
        "table_counts": table_counts,
    }


def run_database_backup_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    if parameters.get("contract_version") != BACKUP_CONTRACT_VERSION:
        raise job_service.JobStateError("Unsupported database backup contract version.")
    if parameters.get("raw_files_included") is not False:
        raise job_service.JobStateError("A metadata backup must exclude raw files.")

    source_path = get_settings().database_path.resolve()
    if parameters.get("source_database_name") != source_path.name:
        raise job_service.JobStateError("The database backup source no longer matches settings.")
    if not source_path.is_file():
        raise job_service.JobStateError("The SQLite database file does not exist.")

    expected_revision = parameters.get("expected_revision")
    if expected_revision is not None and not isinstance(expected_revision, str):
        raise job_service.JobStateError("The expected database revision is invalid.")

    filename = f"dataset-manager-metadata-job-{context.job_id}.db"
    context.report_progress(current=0, stage="preparing_backup")
    with job_artifact_service.JobArtifactWorkspace(
        job_artifact_service.job_artifact_root(),
        job_id=context.job_id,
        filename=filename,
        media_type=BACKUP_MEDIA_TYPE,
    ) as workspace:
        page_count = _copy_database(source_path, workspace.path, context=context)
        context.report_progress(
            current=page_count,
            total=page_count,
            stage="verifying_backup",
        )
        verification = _inspect_backup(workspace.path)
        if verification["current_revision"] != expected_revision:
            raise RuntimeError(
                "The backup schema revision does not match the creation snapshot."
            )
        context.report_progress(
            current=page_count,
            total=page_count,
            stage="hashing_backup",
        )
        metadata = workspace.finalize(checkpoint=context.checkpoint)
        context.checkpoint()

    return {
        "artifact": {
            "filename": metadata.filename,
            "media_type": metadata.media_type,
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
        },
        "verification": verification,
        "raw_files_included": False,
        "contract_version": BACKUP_CONTRACT_VERSION,
    }
