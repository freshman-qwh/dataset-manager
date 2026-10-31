import type { Job } from "./job";

export interface ValidationRuntime {
  ready: boolean; python_path: string | null; message: string;
  versions: Record<string, string>; base_python: string | null; install_job: Job | null;
}

export interface ValidationRun {
  id: string; dataset_id: number; dataset_revision: number; name: string;
  mode: "evaluation" | "exploration" | "batch";
  recipe: {model: "padim" | "patchcore"; image_size: number; roi: NormalizedRoi | null; [key: string]: unknown};
  parent_run_id: string | null; job: Job | null; created_at: string;
  current_dataset_revision: number; summary: Record<string, unknown> | null;
}

export interface NormalizedRoi {x: number; y: number; width: number; height: number}

export interface ValidationMetrics {
  total: number; known: number; unknown: number; normal: number; abnormal: number;
  true_positive: number; false_positive: number; false_negative: number; true_negative: number;
  false_positive_rate: number | null; recall: number | null; precision: number | null;
  f1: number | null; auroc: number | null;
}
export interface ValidationDecision {
  threshold: number; validation: ValidationMetrics; test: ValidationMetrics | null;
  reused_test_hashes: number; independent_test: boolean; note: string;
}
export interface ValidationResults {
  run: ValidationRun; threshold: number; threshold_source: string;
  threshold_range: {min:number; max:number}; validation_metrics: ValidationMetrics;
  frozen_decision: ValidationDecision | null; test_locked: boolean;
  reference_sample_id: number | null; map_scale: number;
  histogram: Array<{left:number;right:number;normal:number;abnormal:number;unknown:number}>;
  total_seconds: number; fit_seconds: number; notes: string[];
}
export interface ValidationPrediction {
  sample_id: number; relative_path: string; sha256: string; split: string; label_index: number | null;
  capture_group_id: string | null; capture_batch_id: string | null; score: number;
  predicted_label: number; category: string; judgment_changed: boolean; current_sample_available: boolean;
}
export interface ValidationPredictions {
  items: ValidationPrediction[]; total:number;page:number;page_size:number;threshold:number;
}
