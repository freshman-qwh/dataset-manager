import type { Sample } from "./dataset";

export type TriageStatus = "untriaged" | "pending" | "ok" | "ng";
export type OkGrade = "clear" | "borderline";
export type DefectSeverity = "mild" | "moderate" | "severe";
export type TriageQueueScope = "untriaged" | "pending" | "current_filter" | "current_split";
export type NgGrouping = "none" | "defect_type" | "severity" | "defect_type_and_severity";

export interface DefectType {
  id: number;
  dataset_id: number;
  name: string;
  code: string;
  parent_id: number | null;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DefectTypeCreate {
  name: string;
  code?: string | null;
  parent_id?: number | null;
  description?: string | null;
}

export interface TriagePolicyValues {
  split_ok: boolean;
  ng_grouping: NgGrouping;
  instructions: string;
  clear_ok_definition: string;
  borderline_ok_definition: string;
  mild_definition: string;
  moderate_definition: string;
  severe_definition: string;
}

export interface TriagePolicy extends TriagePolicyValues {
  dataset_id: number;
  version: number;
}

export interface SampleTriage {
  sample_id: number;
  dataset_id: number;
  file_hash: string;
  triage_status: TriageStatus;
  ok_grade: OkGrade | null;
  defect_severity: DefectSeverity | null;
  defect_types: DefectType[];
  primary_defect_type_id: number | null;
  triage_note: string | null;
  triage_version: number;
  triaged_at: string | null;
  triage_policy_version: number | null;
  current_policy_version: number;
  outdated: boolean;
}

export interface SampleTriageWrite {
  expected_version: number;
  expected_file_hash: string;
  triage_status: TriageStatus;
  ok_grade?: OkGrade | null;
  defect_severity?: DefectSeverity | null;
  defect_type_ids?: number[];
  primary_defect_type_id?: number | null;
  triage_note?: string | null;
}

export interface TriageNavigation {
  current_sample: Sample | null;
  previous_sample: Sample | null;
  next_sample: Sample | null;
  current_index: number | null;
  total: number;
  remaining: number;
  queue_scope: TriageQueueScope;
}

export interface TriageStats {
  dataset_id: number;
  total_images: number;
  by_status: Record<string, number>;
  by_ok_grade: Record<string, number>;
  by_severity: Record<string, number>;
  by_defect_type: Record<string, number>;
  by_export_bucket: Record<string, number>;
  outdated: number;
}
