import type { Dataset } from "./dataset";

export interface DatasetCardSummary {
  sample_count: number;
  image_count: number;
  normal_count: number;
  anomaly_count: number;
  pending_count: number;
  untriaged_count: number;
  unavailable_count: number;
  mask_count: number;
  category_count: number;
  batch_count: number;
  splits: { train: number; val: number; test: number; unassigned: number };
}

export interface DatasetCardCategory {
  id: number;
  name: string;
  sample_count: number;
  normal_count: number;
  anomaly_count: number;
}

export interface DatasetCardPreview {
  sample_id: number;
  filename: string;
  file_hash: string;
  category_name: string | null;
  label: string | null;
}

export interface DatasetCard {
  dataset: Dataset;
  generated_at: string;
  summary: DatasetCardSummary;
  categories: DatasetCardCategory[];
  preview_samples: DatasetCardPreview[];
}
