export type DatabaseIntegrityStatus = "healthy" | "attention" | "migration_required";

export interface DatabaseSchemaIssue {
  code: string;
  title: string;
  detail: string;
}

export interface ForeignKeyViolation {
  table: string;
  row_id: string;
  parent_table: string;
  foreign_key_index: number;
}

export interface DatabaseRepairAction {
  action_id: string;
  title: string;
  description: string;
  operation: "delete" | "update";
  affected_rows: number;
  record_ids: string[];
  truncated_record_ids: number;
}

export interface DatabaseIntegrityReport {
  generated_at: string;
  status: DatabaseIntegrityStatus;
  database_name: string;
  quick_check: string;
  current_revision: string | null;
  head_revision: string;
  schema_issues: DatabaseSchemaIssue[];
  foreign_key_violation_count: number;
  foreign_key_violations: ForeignKeyViolation[];
  truncated_foreign_key_violations: number;
  repair_actions: DatabaseRepairAction[];
  affected_row_count: number;
  report_token: string;
}

export interface DatabaseRepairPreview {
  report_token: string;
  selected_actions: DatabaseRepairAction[];
  affected_row_count: number;
  confirmation_text: string;
  backup_required: boolean;
}

export interface DatabaseRepairActionResult {
  action_id: string;
  primary_rows: number;
  deleted_rows: number;
  updated_rows: number;
}

export interface DatabaseRepairResult {
  backup_path: string;
  backup_quick_check: string;
  action_results: DatabaseRepairActionResult[];
  deleted_rows: number;
  updated_rows: number;
  before_affected_row_count: number;
  after_affected_row_count: number;
  report: DatabaseIntegrityReport;
}
