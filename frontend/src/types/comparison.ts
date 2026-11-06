import type { Sample } from "./dataset";

export type ComparisonSideName = "normal" | "anomaly";

export interface ComparisonSide {
  items: Sample[];
  total: number;
  page: number;
  page_size: number;
}

export interface ComparisonRead {
  dataset_id: number;
  category_id: number | null;
  batch_id: number | null;
  normal: ComparisonSide;
  anomaly: ComparisonSide;
  excluded_count: number;
}

export interface ComparisonQuery {
  category_id?: number;
  batch_id?: number;
  normal_page: number;
  anomaly_page: number;
  page_size: number;
}
