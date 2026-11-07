import type { Sample } from "./dataset";

export interface WorkpieceViews {
  dataset_id: number;
  anchor_sample_id: number;
  capture_group_id: string | null;
  capture_batch_id: string | null;
  dataset_revision: number;
  items: Sample[];
  total: number;
  page: number;
  page_size: number;
  isolation: {
    total: number;
    normal_candidate: boolean;
    reasons: Record<string, number>;
  };
}
