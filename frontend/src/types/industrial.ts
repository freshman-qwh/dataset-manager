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
  mode: "selected" | "directories" | "mapping";
  sample_ids?: number[];
  capture_group_id?: string | null;
  capture_batch_id?: string | null;
  mapping_text?: string;
  path_column?: string;
  group_column?: string;
  batch_column?: string;
}
