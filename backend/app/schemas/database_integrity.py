from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DatabaseSchemaIssue(BaseModel):
    code: str
    title: str
    detail: str


class ForeignKeyViolation(BaseModel):
    table: str
    row_id: str
    parent_table: str
    foreign_key_index: int


class DatabaseRepairAction(BaseModel):
    action_id: str
    title: str
    description: str
    operation: Literal["delete", "update"]
    affected_rows: int
    record_ids: list[str]
    truncated_record_ids: int = 0


class DatabaseIntegrityReport(BaseModel):
    generated_at: datetime
    status: Literal["healthy", "attention", "migration_required"]
    database_name: str
    quick_check: str
    current_revision: str | None
    head_revision: str
    schema_issues: list[DatabaseSchemaIssue]
    foreign_key_violation_count: int
    foreign_key_violations: list[ForeignKeyViolation]
    truncated_foreign_key_violations: int
    repair_actions: list[DatabaseRepairAction]
    affected_row_count: int
    report_token: str


class DatabaseRepairPreviewRequest(BaseModel):
    action_ids: list[str] = Field(min_length=1)


class DatabaseRepairPreview(BaseModel):
    report_token: str
    selected_actions: list[DatabaseRepairAction]
    affected_row_count: int
    confirmation_text: str
    backup_required: bool = True


class DatabaseRepairRequest(BaseModel):
    report_token: str = Field(min_length=1)
    action_ids: list[str] = Field(min_length=1)
    confirmation: str


class DatabaseRepairActionResult(BaseModel):
    action_id: str
    primary_rows: int
    deleted_rows: int
    updated_rows: int


class DatabaseRepairResult(BaseModel):
    backup_path: str
    backup_quick_check: str
    action_results: list[DatabaseRepairActionResult]
    deleted_rows: int
    updated_rows: int
    before_affected_row_count: int
    after_affected_row_count: int
    report: DatabaseIntegrityReport
