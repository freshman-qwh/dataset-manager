from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session

from app import models  # noqa: F401
from app.core.migrations import create_verified_backup, head_revision
from app.schemas.database_integrity import (
    DatabaseIntegrityReport,
    DatabaseRepairAction,
    DatabaseRepairActionResult,
    DatabaseRepairPreview,
    DatabaseRepairResult,
    DatabaseSchemaIssue,
    ForeignKeyViolation,
)


CONFIRMATION_PREFIX = "确认清理"
MAX_DETAIL_IDS = 100


class DatabaseIntegrityError(ValueError):
    """Base error for invalid integrity maintenance requests."""


class DatabaseIntegrityConflictError(DatabaseIntegrityError):
    """Raised when a report token no longer matches current database state."""


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    title: str
    description: str
    operation: str
    required_tables: frozenset[str]
    identity_query: str


ACTION_DEFINITIONS = (
    ActionDefinition(
        action_id="delete_orphan_samples",
        title="清理无所属数据集的样本记录",
        description="删除找不到所属数据集的样本元数据，并同步清理其标签关联和标注。原始文件不会删除。",
        operation="delete",
        required_tables=frozenset({"datasets", "samples"}),
        identity_query=(
            "SELECT CAST(samples.id AS TEXT) FROM samples "
            "LEFT JOIN datasets ON datasets.id = samples.dataset_id "
            "WHERE datasets.id IS NULL ORDER BY samples.id"
        ),
    ),
    ActionDefinition(
        action_id="delete_orphan_annotations",
        title="清理无所属样本或数据集的标注",
        description="删除无法关联到有效样本或数据集的标注元数据。",
        operation="delete",
        required_tables=frozenset({"annotations", "datasets", "samples"}),
        identity_query=(
            "SELECT CAST(annotations.id AS TEXT) FROM annotations "
            "LEFT JOIN samples ON samples.id = annotations.sample_id "
            "LEFT JOIN datasets ON datasets.id = annotations.dataset_id "
            "WHERE samples.id IS NULL OR datasets.id IS NULL "
            "ORDER BY annotations.id"
        ),
    ),
    ActionDefinition(
        action_id="clear_missing_annotation_class_refs",
        title="解除失效的标注类别引用",
        description="保留标注与类别名称，只把找不到类别记录的 class_id 置空。",
        operation="update",
        required_tables=frozenset({"annotations", "annotation_classes"}),
        identity_query=(
            "SELECT CAST(annotations.id AS TEXT) FROM annotations "
            "LEFT JOIN annotation_classes ON annotation_classes.id = annotations.class_id "
            "WHERE annotations.class_id IS NOT NULL AND annotation_classes.id IS NULL "
            "ORDER BY annotations.id"
        ),
    ),
    ActionDefinition(
        action_id="clear_missing_annotation_tag_refs",
        title="解除失效的旧标签引用",
        description="保留标注，只把找不到标签记录的兼容 tag_id 置空。",
        operation="update",
        required_tables=frozenset({"annotations", "tags"}),
        identity_query=(
            "SELECT CAST(annotations.id AS TEXT) FROM annotations "
            "LEFT JOIN tags ON tags.id = annotations.tag_id "
            "WHERE annotations.tag_id IS NOT NULL AND tags.id IS NULL "
            "ORDER BY annotations.id"
        ),
    ),
    ActionDefinition(
        action_id="delete_orphan_sample_tag_links",
        title="清理失效的样本标签关联",
        description="删除找不到样本或标签的关联记录，不删除有效样本和标签。",
        operation="delete",
        required_tables=frozenset({"sample_tag_links", "samples", "tags"}),
        identity_query=(
            "SELECT CAST(sample_tag_links.sample_id AS TEXT) || ':' || "
            "CAST(sample_tag_links.tag_id AS TEXT) FROM sample_tag_links "
            "LEFT JOIN samples ON samples.id = sample_tag_links.sample_id "
            "LEFT JOIN tags ON tags.id = sample_tag_links.tag_id "
            "WHERE samples.id IS NULL OR tags.id IS NULL "
            "ORDER BY sample_tag_links.sample_id, sample_tag_links.tag_id"
        ),
    ),
    ActionDefinition(
        action_id="delete_orphan_annotation_classes",
        title="清理无所属数据集的标注类别",
        description="先解除相关标注引用，再删除找不到所属数据集的类别元数据。",
        operation="delete",
        required_tables=frozenset({"annotation_classes", "annotations", "datasets"}),
        identity_query=(
            "SELECT CAST(annotation_classes.id AS TEXT) FROM annotation_classes "
            "LEFT JOIN datasets ON datasets.id = annotation_classes.dataset_id "
            "WHERE datasets.id IS NULL ORDER BY annotation_classes.id"
        ),
    ),
    ActionDefinition(
        action_id="delete_orphan_tags",
        title="清理无所属数据集的标签",
        description="解除相关标注和层级引用、删除关联后，再清理无所属数据集的标签元数据。",
        operation="delete",
        required_tables=frozenset(
            {"datasets", "tags", "annotations", "sample_tag_links"}
        ),
        identity_query=(
            "SELECT CAST(tags.id AS TEXT) FROM tags "
            "LEFT JOIN datasets ON datasets.id = tags.dataset_id "
            "WHERE datasets.id IS NULL ORDER BY tags.id"
        ),
    ),
    ActionDefinition(
        action_id="clear_invalid_tag_parents",
        title="解除失效的标签父级",
        description="保留标签，只把不存在或跨数据集的父级引用置空。",
        operation="update",
        required_tables=frozenset({"tags"}),
        identity_query=(
            "SELECT CAST(child.id AS TEXT) FROM tags AS child "
            "LEFT JOIN tags AS parent ON parent.id = child.parent_id "
            "WHERE child.parent_id IS NOT NULL "
            "AND (parent.id IS NULL OR parent.dataset_id <> child.dataset_id) "
            "ORDER BY child.id"
        ),
    ),
    ActionDefinition(
        action_id="delete_orphan_training_readiness",
        title="清理无所属数据集的训练准备记录",
        description="删除找不到所属数据集的训练准备配置元数据。",
        operation="delete",
        required_tables=frozenset({"datasets", "training_readiness_states"}),
        identity_query=(
            "SELECT CAST(training_readiness_states.id AS TEXT) "
            "FROM training_readiness_states "
            "LEFT JOIN datasets ON datasets.id = training_readiness_states.dataset_id "
            "WHERE datasets.id IS NULL ORDER BY training_readiness_states.id"
        ),
    ),
)

ACTION_BY_ID = {
    definition.action_id: definition for definition in ACTION_DEFINITIONS
}


def _current_revision(session: Session, table_names: set[str]) -> str | None:
    if "alembic_version" not in table_names:
        return None
    row = session.exec(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
    return str(row[0]) if row else None


def _schema_issues(session: Session, table_names: set[str]) -> list[DatabaseSchemaIssue]:
    issues: list[DatabaseSchemaIssue] = []
    inspector = inspect(session.get_bind())
    for table_name, table in sorted(SQLModel.metadata.tables.items()):
        if table_name not in table_names:
            issues.append(
                DatabaseSchemaIssue(
                    code=f"missing_table:{table_name}",
                    title=f"缺少数据表 {table_name}",
                    detail="请先停止后端并运行正式数据库升级命令。",
                )
            )
            continue
        existing_columns = {
            str(column["name"]) for column in inspector.get_columns(table_name)
        }
        for column in table.columns:
            if column.name not in existing_columns:
                issues.append(
                    DatabaseSchemaIssue(
                        code=f"missing_column:{table_name}.{column.name}",
                        title=f"缺少字段 {table_name}.{column.name}",
                        detail="请先停止后端并运行正式数据库升级命令。",
                    )
                )
    return issues


def _collect_action(
    session: Session,
    definition: ActionDefinition,
    table_names: set[str],
) -> tuple[DatabaseRepairAction | None, str]:
    digest = sha256()
    count = 0
    record_ids: list[str] = []
    if not definition.required_tables.issubset(table_names):
        return None, f"{definition.action_id}:unavailable"

    for row in session.exec(text(definition.identity_query)):
        record_id = str(row[0])
        digest.update(record_id.encode("utf-8"))
        digest.update(b"\0")
        count += 1
        if len(record_ids) < MAX_DETAIL_IDS:
            record_ids.append(record_id)
    if count == 0:
        return None, f"{definition.action_id}:0"

    action = DatabaseRepairAction(
        action_id=definition.action_id,
        title=definition.title,
        description=definition.description,
        operation=definition.operation,
        affected_rows=count,
        record_ids=record_ids,
        truncated_record_ids=max(0, count - len(record_ids)),
    )
    return action, f"{definition.action_id}:{count}:{digest.hexdigest()}"


def _foreign_key_violations(
    session: Session,
) -> tuple[int, list[ForeignKeyViolation], int, str]:
    digest = sha256()
    count = 0
    violations: list[ForeignKeyViolation] = []
    for row in session.exec(text("PRAGMA foreign_key_check")):
        table, row_id, parent_table, foreign_key_index = row
        identifier = f"{table}:{row_id}:{parent_table}:{foreign_key_index}"
        digest.update(identifier.encode("utf-8"))
        digest.update(b"\0")
        count += 1
        if len(violations) < MAX_DETAIL_IDS:
            violations.append(
                ForeignKeyViolation(
                    table=str(table),
                    row_id=str(row_id),
                    parent_table=str(parent_table),
                    foreign_key_index=int(foreign_key_index),
                )
            )
    return count, violations, max(0, count - len(violations)), digest.hexdigest()


def build_integrity_report(
    session: Session,
    *,
    database_name: str,
) -> DatabaseIntegrityReport:
    inspector = inspect(session.get_bind())
    table_names = set(inspector.get_table_names())
    quick_row = session.exec(text("PRAGMA quick_check")).first()
    quick_check = str(quick_row[0]) if quick_row else "missing result"
    schema_issues = _schema_issues(session, table_names)
    foreign_key_count, foreign_keys, truncated_foreign_keys, foreign_key_digest = (
        _foreign_key_violations(session)
    )

    actions: list[DatabaseRepairAction] = []
    action_tokens: list[str] = []
    for definition in ACTION_DEFINITIONS:
        action, token = _collect_action(session, definition, table_names)
        action_tokens.append(token)
        if action is not None:
            actions.append(action)

    current = _current_revision(session, table_names)
    target = head_revision()
    token_payload = "|".join(
        [
            quick_check,
            current or "unversioned",
            target,
            foreign_key_digest,
            *(issue.code for issue in schema_issues),
            *action_tokens,
        ]
    )
    report_token = sha256(token_payload.encode("utf-8")).hexdigest()
    affected_row_count = sum(action.affected_rows for action in actions)
    if schema_issues or quick_check.lower() != "ok" or current != target:
        status = "migration_required"
    elif foreign_key_count or actions:
        status = "attention"
    else:
        status = "healthy"

    return DatabaseIntegrityReport(
        generated_at=datetime.now(timezone.utc),
        status=status,
        database_name=database_name,
        quick_check=quick_check,
        current_revision=current,
        head_revision=target,
        schema_issues=schema_issues,
        foreign_key_violation_count=foreign_key_count,
        foreign_key_violations=foreign_keys,
        truncated_foreign_key_violations=truncated_foreign_keys,
        repair_actions=actions,
        affected_row_count=affected_row_count,
        report_token=report_token,
    )


def build_repair_preview(
    report: DatabaseIntegrityReport,
    action_ids: list[str],
) -> DatabaseRepairPreview:
    if report.status == "migration_required":
        raise DatabaseIntegrityError(
            "Database migration must reach the current head before metadata repair."
        )
    requested = list(dict.fromkeys(action_ids))
    unknown = [action_id for action_id in requested if action_id not in ACTION_BY_ID]
    if unknown:
        raise DatabaseIntegrityError(
            f"Unknown repair actions: {', '.join(unknown)}"
        )
    actions_by_id = {action.action_id: action for action in report.repair_actions}
    unavailable = [
        action_id for action_id in requested if action_id not in actions_by_id
    ]
    if unavailable:
        raise DatabaseIntegrityConflictError(
            "The selected issues are no longer present. Refresh the integrity report."
        )
    selected = [actions_by_id[action_id] for action_id in requested]
    affected = sum(action.affected_rows for action in selected)
    return DatabaseRepairPreview(
        report_token=report.report_token,
        selected_actions=selected,
        affected_row_count=affected,
        confirmation_text=f"{CONFIRMATION_PREFIX} {affected} 条孤立元数据",
    )


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return max(0, int(value or 0))


def _execute_action(session: Session, action_id: str, primary_rows: int) -> DatabaseRepairActionResult:
    deleted_rows = 0
    updated_rows = 0

    if action_id == "delete_orphan_samples":
        condition = "sample_id IN (SELECT samples.id FROM samples LEFT JOIN datasets ON datasets.id = samples.dataset_id WHERE datasets.id IS NULL)"
        deleted_rows += _rowcount(
            session.exec(text(f"DELETE FROM sample_tag_links WHERE {condition}"))
        )
        deleted_rows += _rowcount(
            session.exec(text(f"DELETE FROM annotations WHERE {condition}"))
        )
        deleted_rows += _rowcount(
            session.exec(
                text(
                    "DELETE FROM samples WHERE NOT EXISTS "
                    "(SELECT 1 FROM datasets WHERE datasets.id = samples.dataset_id)"
                )
            )
        )
    elif action_id == "delete_orphan_annotations":
        deleted_rows += _rowcount(
            session.exec(
                text(
                    "DELETE FROM annotations WHERE "
                    "NOT EXISTS (SELECT 1 FROM samples WHERE samples.id = annotations.sample_id) "
                    "OR NOT EXISTS (SELECT 1 FROM datasets WHERE datasets.id = annotations.dataset_id)"
                )
            )
        )
    elif action_id == "clear_missing_annotation_class_refs":
        updated_rows += _rowcount(
            session.exec(
                text(
                    "UPDATE annotations SET class_id = NULL "
                    "WHERE class_id IS NOT NULL AND NOT EXISTS "
                    "(SELECT 1 FROM annotation_classes "
                    "WHERE annotation_classes.id = annotations.class_id)"
                )
            )
        )
    elif action_id == "clear_missing_annotation_tag_refs":
        updated_rows += _rowcount(
            session.exec(
                text(
                    "UPDATE annotations SET tag_id = NULL "
                    "WHERE tag_id IS NOT NULL AND NOT EXISTS "
                    "(SELECT 1 FROM tags WHERE tags.id = annotations.tag_id)"
                )
            )
        )
    elif action_id == "delete_orphan_sample_tag_links":
        deleted_rows += _rowcount(
            session.exec(
                text(
                    "DELETE FROM sample_tag_links WHERE "
                    "NOT EXISTS (SELECT 1 FROM samples "
                    "WHERE samples.id = sample_tag_links.sample_id) "
                    "OR NOT EXISTS (SELECT 1 FROM tags "
                    "WHERE tags.id = sample_tag_links.tag_id)"
                )
            )
        )
    elif action_id == "delete_orphan_annotation_classes":
        orphan_ids = (
            "SELECT annotation_classes.id FROM annotation_classes "
            "LEFT JOIN datasets ON datasets.id = annotation_classes.dataset_id "
            "WHERE datasets.id IS NULL"
        )
        updated_rows += _rowcount(
            session.exec(
                text(
                    f"UPDATE annotations SET class_id = NULL "
                    f"WHERE class_id IN ({orphan_ids})"
                )
            )
        )
        deleted_rows += _rowcount(
            session.exec(
                text(
                    "DELETE FROM annotation_classes WHERE NOT EXISTS "
                    "(SELECT 1 FROM datasets "
                    "WHERE datasets.id = annotation_classes.dataset_id)"
                )
            )
        )
    elif action_id == "delete_orphan_tags":
        orphan_ids = (
            "SELECT tags.id FROM tags "
            "LEFT JOIN datasets ON datasets.id = tags.dataset_id "
            "WHERE datasets.id IS NULL"
        )
        deleted_rows += _rowcount(
            session.exec(
                text(
                    f"DELETE FROM sample_tag_links WHERE tag_id IN ({orphan_ids})"
                )
            )
        )
        updated_rows += _rowcount(
            session.exec(
                text(
                    f"UPDATE annotations SET tag_id = NULL WHERE tag_id IN ({orphan_ids})"
                )
            )
        )
        updated_rows += _rowcount(
            session.exec(
                text(
                    f"UPDATE tags SET parent_id = NULL WHERE parent_id IN ({orphan_ids})"
                )
            )
        )
        deleted_rows += _rowcount(
            session.exec(
                text(
                    "DELETE FROM tags WHERE NOT EXISTS "
                    "(SELECT 1 FROM datasets WHERE datasets.id = tags.dataset_id)"
                )
            )
        )
    elif action_id == "clear_invalid_tag_parents":
        updated_rows += _rowcount(
            session.exec(
                text(
                    "UPDATE tags AS child SET parent_id = NULL "
                    "WHERE child.parent_id IS NOT NULL AND NOT EXISTS "
                    "(SELECT 1 FROM tags AS parent "
                    "WHERE parent.id = child.parent_id "
                    "AND parent.dataset_id = child.dataset_id)"
                )
            )
        )
    elif action_id == "delete_orphan_training_readiness":
        deleted_rows += _rowcount(
            session.exec(
                text(
                    "DELETE FROM training_readiness_states WHERE NOT EXISTS "
                    "(SELECT 1 FROM datasets "
                    "WHERE datasets.id = training_readiness_states.dataset_id)"
                )
            )
        )
    else:
        raise DatabaseIntegrityError(f"Unsupported repair action: {action_id}")

    return DatabaseRepairActionResult(
        action_id=action_id,
        primary_rows=primary_rows,
        deleted_rows=deleted_rows,
        updated_rows=updated_rows,
    )


def repair_integrity(
    session: Session,
    *,
    database_path: Path,
    report_token: str,
    action_ids: list[str],
    confirmation: str,
) -> DatabaseRepairResult:
    before = build_integrity_report(session, database_name=database_path.name)
    if before.report_token != report_token:
        raise DatabaseIntegrityConflictError(
            "The database changed after the preview. Refresh and review it again."
        )
    preview = build_repair_preview(before, action_ids)
    if confirmation != preview.confirmation_text:
        raise DatabaseIntegrityError(
            "Confirmation text does not match the current repair preview."
        )

    session.rollback()
    session.exec(text("BEGIN IMMEDIATE"))
    try:
        current = build_integrity_report(session, database_name=database_path.name)
        if current.report_token != report_token:
            raise DatabaseIntegrityConflictError(
                "The database changed before the repair lock was acquired. "
                "No repair was applied."
            )

        backup = create_verified_backup(database_path)
        primary_rows = {
            action.action_id: action.affected_rows
            for action in preview.selected_actions
        }
        results: list[DatabaseRepairActionResult] = []
        for definition in ACTION_DEFINITIONS:
            if definition.action_id in primary_rows:
                results.append(
                    _execute_action(
                        session,
                        definition.action_id,
                        primary_rows[definition.action_id],
                    )
                )
        session.commit()
    except Exception:
        session.rollback()
        raise

    after = build_integrity_report(session, database_name=database_path.name)
    return DatabaseRepairResult(
        backup_path=backup.backup_path,
        backup_quick_check=backup.quick_check,
        action_results=results,
        deleted_rows=sum(result.deleted_rows for result in results),
        updated_rows=sum(result.updated_rows for result in results),
        before_affected_row_count=before.affected_row_count,
        after_affected_row_count=after.affected_row_count,
        report=after,
    )
