import type {
  Dataset,
  DatasetStats,
  DuplicateReport,
  Sample,
  Tag
} from "../types/dataset";

const MAX_CACHE_AGE_MS = 5 * 60 * 1000;
const MAX_CACHE_ENTRIES = 3;

export interface DatasetDetailFilters {
  search: string;
  fileType: string;
  fileStatus: string;
  tag: string;
  split: string;
  reviewStatus: string;
  annotationProgress: string;
  page: number;
  pageSize: number;
  sortBy: string;
  sortOrder: "asc" | "desc";
}

export interface DatasetDetailCacheEntry {
  datasetId: number;
  dataset: Dataset | null;
  stats: DatasetStats | null;
  samples: Sample[];
  sampleTotal: number;
  duplicateReport: DuplicateReport | null;
  availableTags: Tag[];
  filters: DatasetDetailFilters;
  savedAt: number;
}

const cache = new Map<number, DatasetDetailCacheEntry>();

export function readDatasetDetailCache(datasetId: number): DatasetDetailCacheEntry | null {
  const entry = cache.get(datasetId);
  if (!entry) {
    return null;
  }
  if (Date.now() - entry.savedAt > MAX_CACHE_AGE_MS) {
    cache.delete(datasetId);
    return null;
  }
  cache.delete(datasetId);
  cache.set(datasetId, entry);
  return entry;
}

export function writeDatasetDetailCache(entry: DatasetDetailCacheEntry): void {
  cache.delete(entry.datasetId);
  cache.set(entry.datasetId, entry);
  while (cache.size > MAX_CACHE_ENTRIES) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) {
      break;
    }
    cache.delete(oldestKey);
  }
}

export function invalidateDatasetDetailCache(datasetId: number): void {
  cache.delete(datasetId);
}
