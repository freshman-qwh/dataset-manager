import type { Sample } from "./dataset";

export interface LookupCandidate {
  id: number;
  filename: string;
  relative_path: string;
  absolute_path: string;
  file_status: string;
  file_hash: string;
}
export interface FilenameLookupResult {
  entry: string;
  total: number;
  candidates: LookupCandidate[];
  page: number;
  page_size: number;
}
export interface FilenameLookupRead {
  dataset_id: number;
  duplicate_count: number;
  blank_count: number;
  results: FilenameLookupResult[];
}
export type CoverageStatus = "all" | "normal" | "anomaly" | "pending" | "untriaged" | "stale" | "unavailable";
export interface CoverageAxis { id: number | null; name: string }
export interface CoverageCounts {
  total: number; normal: number; anomaly: number; pending: number;
  untriaged: number; stale: number; unavailable: number;
}
export interface CoverageCell extends CoverageCounts { category_id: number | null; batch_id: number | null }
export interface CoverageRead {
  dataset_id: number;
  categories: CoverageAxis[];
  batches: CoverageAxis[];
  cells: CoverageCell[];
  totals: CoverageCounts;
}
export interface CoverageSamplesRead { items: Sample[]; total: number; page: number; page_size: number }
