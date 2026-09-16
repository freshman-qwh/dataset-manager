import type { Job } from "./job";
import type { DefectSeverity, DefectType, OkGrade, TriagePolicy } from "./triage";

export type DirectoryMappingStatus = "ok" | "ng" | "pending";
export type DirectoryMappingExistingBehavior = "skip" | "overwrite";
export type DirectoryMappingDecision =
  | "apply"
  | "unchanged"
  | "skipped_existing"
  | "unmapped"
  | "file_unavailable";

export interface TriageDirectorySource {
  directory: string;
  image_count: number;
  untriaged_count: number;
  existing_count: number;
  status_counts: Record<string, number>;
  examples: string[];
}

export interface TriageDirectorySourceResponse {
  dataset_id: number;
  dataset_revision: number;
  triage_policy: TriagePolicy;
  defect_types: DefectType[];
  total_directories: number;
  total_images: number;
  page: number;
  page_size: number;
  page_count: number;
  items: TriageDirectorySource[];
}

export interface TriageDirectoryMappingRule {
  source_directory: string;
  triage_status: DirectoryMappingStatus;
  ok_grade?: OkGrade;
  defect_severity?: DefectSeverity;
  defect_type_id?: number;
}

export interface TriageDirectoryMappingPreviewRequest {
  mappings: TriageDirectoryMappingRule[];
  existing_behavior: DirectoryMappingExistingBehavior;
}

export interface TriageDirectoryMappingPreviewItem {
  sample_id: number;
  relative_path: string;
  source_directory: string;
  current_status: string;
  target_status: DirectoryMappingStatus | null;
  target_ok_grade: OkGrade | null;
  target_defect_severity: DefectSeverity | null;
  target_defect_type_id: number | null;
  decision: DirectoryMappingDecision;
}

export interface TriageDirectoryMappingPreviewResponse {
  dataset_id: number;
  plan_id: string;
  plan_hash: string;
  created_at: string;
  expires_at: string;
  existing_behavior: DirectoryMappingExistingBehavior;
  total_images: number;
  mapped_sample_count: number;
  change_count: number;
  unchanged_count: number;
  skipped_existing_count: number;
  unmapped_count: number;
  unavailable_count: number;
  blocked: boolean;
  page: number;
  page_size: number;
  page_count: number;
  items: TriageDirectoryMappingPreviewItem[];
}

export interface TriageDirectoryMappingJobCreateResponse {
  job: Job;
  created: boolean;
}
