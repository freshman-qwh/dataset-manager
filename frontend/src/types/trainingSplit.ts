export type TrainingSplit = "train" | "val" | "test";

export interface TrainingSplitRequest {
  train_ratio: number;
  val_ratio: number;
  test_ratio: number;
  include_test: boolean;
  include_empty: boolean;
  triage_filter: "all" | "ok" | "ng";
  seed: number;
  overrides: Record<number, TrainingSplit | null>;
  page: number;
  page_size: number;
}

export interface TrainingSplitRow {
  sample_id: number;
  relative_path: string;
  annotation_progress: string;
  triage_status: string;
  current_split: string | null;
  suggested_split: TrainingSplit | null;
  duplicate_count: number;
  warning: string | null;
}

export interface TrainingSplitPreview {
  dataset_id: number;
  fingerprint: string;
  candidate_count: number;
  unassigned_count: number;
  duplicate_group_count: number;
  excluded_counts: Record<string, number>;
  change_count: number;
  split_counts: Record<string, number>;
  blocked: boolean;
  warnings: string[];
  page: number;
  page_count: number;
  rows: TrainingSplitRow[];
}

export interface TrainingSplitCommitResult {
  updated: number;
  sample_ids: number[];
  split_counts: Record<string, number>;
  dataset_revision: number;
}
