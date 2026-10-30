export interface FrozenPlan {
  plan_id: string;
  plan_hash: string;
  kind: string;
  dataset_id: number;
  dataset_revision: number;
  expires_at: number;
  summary: Record<string, unknown>;
  confirmation: string;
  total: number;
  page: number;
  page_size: number;
  rows: Array<Record<string, string | number | null>>;
}

export interface GroupPreviewRequest {
  mode: "selected" | "directories" | "mapping" | "filename";
  sample_ids?: number[];
  capture_group_id?: string | null;
  capture_batch_id?: string | null;
  mapping_text?: string;
  path_column?: string;
  group_column?: string;
  batch_column?: string;
  filename_rule?: {delimiter: "_" | "-" | " "; keep_segments: number; include_parent: boolean};
  remember_rule?: boolean;
}

export interface IndustrialReadiness {
  total_images: number; normal_candidates: number; normal_groups: number;
  missing_groups: number; needs_review: number;
  next_step: "scan" | "triage" | "review" | "groups" | "prepare";
  next_label: string; explanation: string;
}
