import type { Job } from "./job";
import type { TriagePolicy } from "./triage";

export type DirectoryExportDelivery = "zip" | "directory";

export interface DirectoryExportSampleQuery {
  search?: string;
  file_type?: string;
  file_status?: string;
  tag?: string;
  split?: string;
  review_status?: string;
  annotation_progress?: string;
  sample_ids?: number[];
  triage_status?: string;
  ok_grade?: string;
  defect_severity?: string;
  defect_type_id?: number;
  triage_outdated?: boolean;
  sort_by?: string;
  sort_order?: "asc" | "desc";
}

export interface DirectoryExportPreviewRequest {
  delivery: DirectoryExportDelivery;
  sample_query: DirectoryExportSampleQuery;
  include_pending: boolean;
  include_untriaged: boolean;
  include_outdated: boolean;
  run_name?: string;
}

export interface DirectoryExportPreviewItem {
  sample_id: number;
  source_relative_path: string;
  target_relative_path: string | null;
  bucket: string | null;
  file_size: number;
  triage_status: string;
  outdated: boolean;
  included: boolean;
  exclusion_reason: string | null;
}

export interface DirectoryExportPreviewResponse {
  dataset_id: number;
  plan_id: string;
  plan_hash: string;
  created_at: string;
  expires_at: string;
  delivery: DirectoryExportDelivery;
  output_name: string;
  triage_policy: TriagePolicy;
  selected_count: number;
  included_count: number;
  excluded_count: number;
  total_bytes: number;
  directory_counts: Record<string, number>;
  exclusion_counts: Record<string, number>;
  warnings: string[];
  blocked: boolean;
  page: number;
  page_size: number;
  page_count: number;
  items: DirectoryExportPreviewItem[];
}

export interface DirectoryExportJobCreateResponse {
  job: Job;
  created: boolean;
}
