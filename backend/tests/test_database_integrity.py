from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel, Session

from app import models  # noqa: F401
from app.api import system
from app.core.database import get_session
from app.services import database_integrity_service


def _create_database_with_orphans(database_path: Path):
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (database_integrity_service.head_revision(),),
        )
        connection.exec_driver_sql(
            "INSERT INTO datasets "
            "(id, name, task_type, auto_scan_on_open, created_at, updated_at) "
            "VALUES (1, 'valid', 'detection', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO samples "
            "(id, dataset_id, filename, absolute_path, relative_path, file_size, "
            "extension, file_type, file_hash, file_status, annotation_progress, "
            "review_status, created_at, updated_at) "
            "VALUES "
            "(1, 1, 'valid.jpg', '/raw/valid.jpg', 'valid.jpg', 1, '.jpg', "
            "'image', 'valid-hash', 'normal', 'not_started', 'not_reviewed', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(40, 999, 'orphan.jpg', '/raw/orphan.jpg', 'orphan.jpg', 1, '.jpg', "
            "'image', 'orphan-hash', 'normal', 'not_started', 'not_reviewed', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO annotation_classes "
            "(id, dataset_id, name, created_at, updated_at) VALUES "
            "(10, 999, 'orphan-class', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO tags (id, dataset_id, name, parent_id, created_at) VALUES "
            "(20, 999, 'orphan-tag', NULL, CURRENT_TIMESTAMP), "
            "(21, 1, 'invalid-parent', 999, CURRENT_TIMESTAMP), "
            "(22, 1, 'valid-tag', NULL, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO sample_tag_links (sample_id, tag_id) VALUES "
            "(1, 20), (40, 22), (999, 20)"
        )
        connection.exec_driver_sql(
            "INSERT INTO annotations "
            "(id, sample_id, dataset_id, class_id, tag_id, label, shape_type, "
            "points_json, z_order, locked, hidden, source, created_at, updated_at) "
            "VALUES "
            "(30, 999, 1, NULL, NULL, 'missing-sample', 'rectangle', "
            "'[0,0,1,1]', 0, 0, 0, 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(31, 1, 1, 999, 999, 'missing-refs', 'rectangle', "
            "'[0,0,1,1]', 0, 0, 0, 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(32, 40, 999, 10, 20, 'orphan-sample', 'rectangle', "
            "'[0,0,1,1]', 0, 0, 0, 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO training_readiness_states "
            "(id, dataset_id, task_type, export_format, scope, include_empty, "
            "sample_query_json, class_map_json, saved_at) "
            "VALUES (50, 999, 'detection', 'coco_detection', 'all', 0, "
            "'{}', '[]', CURRENT_TIMESTAMP)"
        )
    return engine


def _action_ids(report) -> set[str]:
    return {action.action_id for action in report.repair_actions}


def test_integrity_report_detects_repairable_orphans(tmp_path: Path) -> None:
    database_path = tmp_path / "integrity.db"
    engine = _create_database_with_orphans(database_path)

    with Session(engine) as session:
        report = database_integrity_service.build_integrity_report(
            session,
            database_name=database_path.name,
        )

    assert report.status == "attention"
    assert report.quick_check == "ok"
    assert report.schema_issues == []
    assert report.foreign_key_violation_count > 0
    assert {
        "delete_orphan_samples",
        "delete_orphan_annotations",
        "clear_missing_annotation_class_refs",
        "clear_missing_annotation_tag_refs",
        "delete_orphan_sample_tag_links",
        "delete_orphan_annotation_classes",
        "delete_orphan_tags",
        "clear_invalid_tag_parents",
        "delete_orphan_training_readiness",
    }.issubset(_action_ids(report))
    engine.dispose()


def test_repair_requires_current_preview_and_exact_confirmation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "integrity.db"
    engine = _create_database_with_orphans(database_path)

    with Session(engine) as session:
        report = database_integrity_service.build_integrity_report(
            session,
            database_name=database_path.name,
        )
        action_ids = [action.action_id for action in report.repair_actions]
        preview = database_integrity_service.build_repair_preview(
            report,
            action_ids,
        )
        with pytest.raises(
            database_integrity_service.DatabaseIntegrityConflictError
        ):
            database_integrity_service.repair_integrity(
                session,
                database_path=database_path,
                report_token="stale-token",
                action_ids=action_ids,
                confirmation=preview.confirmation_text,
            )

        with pytest.raises(database_integrity_service.DatabaseIntegrityError):
            database_integrity_service.repair_integrity(
                session,
                database_path=database_path,
                report_token=report.report_token,
                action_ids=action_ids,
                confirmation="确认清理",
            )

        unchanged = database_integrity_service.build_integrity_report(
            session,
            database_name=database_path.name,
        )
    assert unchanged.report_token == report.report_token
    assert not (tmp_path / "backups").exists()
    engine.dispose()


def test_api_preview_and_confirmed_repair_create_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "integrity.db"
    engine = _create_database_with_orphans(database_path)
    app = FastAPI()
    app.include_router(system.router)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(
        system,
        "get_settings",
        lambda: SimpleNamespace(database_path=database_path),
    )

    with TestClient(app) as client:
        report_response = client.get("/api/system/database-integrity")
        assert report_response.status_code == 200
        report = report_response.json()
        action_ids = [
            action["action_id"] for action in report["repair_actions"]
        ]

        preview_response = client.post(
            "/api/system/database-integrity/repair-preview",
            json={"action_ids": action_ids},
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()

        repair_response = client.post(
            "/api/system/database-integrity/repair",
            json={
                "report_token": preview["report_token"],
                "action_ids": action_ids,
                "confirmation": preview["confirmation_text"],
            },
        )
        assert repair_response.status_code == 200
        result = repair_response.json()

    assert result["backup_quick_check"] == "ok"
    assert Path(result["backup_path"]).is_file()
    assert result["deleted_rows"] > 0
    assert result["updated_rows"] > 0
    assert result["after_affected_row_count"] == 0
    assert result["report"]["status"] == "healthy"

    with Session(engine) as session:
        assert session.exec(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_missing_schema_requires_migration_before_preview(tmp_path: Path) -> None:
    database_path = tmp_path / "partial.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE datasets (id INTEGER PRIMARY KEY, name VARCHAR(160))"
        )

    with Session(engine) as session:
        report = database_integrity_service.build_integrity_report(
            session,
            database_name=database_path.name,
        )

    assert report.status == "migration_required"
    assert any(issue.code == "missing_table:samples" for issue in report.schema_issues)
    with pytest.raises(
        database_integrity_service.DatabaseIntegrityError,
        match="migration",
    ):
        database_integrity_service.build_repair_preview(
            report,
            ["delete_orphan_samples"],
        )
    engine.dispose()
