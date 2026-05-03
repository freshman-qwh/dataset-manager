export interface Dataset {
  id: number;
  name: string;
  description: string | null;
  task_type: string | null;
  root_path: string | null;
  source: string | null;
  modality: string | null;
  license: string | null;
  owner: string | null;
  project: string | null;
  notes: string | null;
  auto_scan_on_open: boolean;
  sample_count: number;
  created_at: string;
  updated_at: string;
}

export interface DatasetCreate {
  name: string;
  description?: string | null;
  task_type?: string | null;
  root_path?: string | null;
  source?: string | null;
  modality?: string | null;
  license?: string | null;
  owner?: string | null;
  project?: string | null;
  notes?: string | null;
  auto_scan_on_open?: boolean;
}

export interface Tag {
  id: number;
  dataset_id: number;
  name: string;
  color: string | null;
  description: string | null;
  parent_id: number | null;
  aliases: string[];
}

export interface TagCreate {
  name: string;
  color?: string | null;
  description?: string | null;
  parent_id?: number | null;
  aliases?: string[];
}

export interface Sample {
  id: number;
  dataset_id: number;
  filename: string;
  absolute_path: string;
  relative_path: string;
  file_size: number;
  extension: string;
  file_type: "image" | "video" | "table" | string;
  mime_type: string | null;
  file_hash: string;
  file_status: string;
  file_modified_at: string | null;
  last_scanned_at: string | null;
  split: string | null;
  review_status: string;
  notes: string | null;
  metadata: Record<string, unknown>;
  tags: Tag[];
  created_at: string;
  updated_at: string;
}

export interface SampleListResponse {
  items: Sample[];
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_order: "asc" | "desc" | string;
}

export interface SampleUpdate {
  split?: string | null;
  review_status?: string | null;
  notes?: string | null;
  tags?: string[];
}

export interface BatchSampleUpdate {
  sample_ids: number[];
  split?: string | null;
  add_tags?: string[];
  replace_tags?: string[];
}

export interface BatchSampleUpdateResult {
  dataset_id: number;
  requested: number;
  updated: number;
  skipped: number;
}

export interface SampleDeleteResult {
  dataset_id: number;
  requested: number;
  deleted: number;
  skipped: number;
}

export interface SamplePreview {
  sample_id: number;
  file_type: string;
  filename: string;
  file_url: string | null;
  columns: string[];
  rows: Record<string, string>[];
  preview_row_count: number;
  error: string | null;
}

export interface DatasetStats {
  dataset_id: number;
  sample_count: number;
  total_size: number;
  by_file_type: Record<string, number>;
  by_extension: Record<string, number>;
  by_status: Record<string, number>;
  by_split: Record<string, number>;
  by_review_status: Record<string, number>;
  tag_counts: Record<string, number>;
  duplicate_groups: number;
  duplicate_samples: number;
  unlabeled_samples: number;
}

export interface ScanResult {
  dataset_id: number;
  root_path: string;
  scanned: number;
  imported: number;
  updated: number;
  unchanged: number;
  missing: number;
  skipped_existing: number;
  skipped_unsupported: number;
  errors: string[];
}

export interface SampleQuery {
  datasetId: number;
  search?: string;
  fileType?: string;
  fileStatus?: string;
  tag?: string;
  split?: string;
  reviewStatus?: string;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
}

export interface DirectoryEntry {
  name: string;
  path: string;
}

export interface DirectoryListResponse {
  current_path: string | null;
  parent_path: string | null;
  entries: DirectoryEntry[];
}

export interface DuplicateGroup {
  file_hash: string;
  count: number;
  samples: Sample[];
}

export interface DuplicateReport {
  dataset_id: number;
  group_count: number;
  duplicate_sample_count: number;
  groups: DuplicateGroup[];
}

export interface MetadataImportRequest {
  file_path: string;
  match_by: string;
  tag_column: string;
  replace_tags: boolean;
}

export interface MetadataImportResult {
  dataset_id: number;
  source_path: string;
  total_rows: number;
  matched: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export interface ExportTemplateResponse {
  dataset_id: number;
  format: string;
  description: string;
  payload: Record<string, unknown>;
}

export interface SplitPlanRequest {
  train_ratio: number;
  val_ratio: number;
  test_ratio: number;
  include_test: boolean;
  stratify_by_tags: boolean;
  normal_only: boolean;
  only_unassigned: boolean;
  seed: number;
}

export interface SplitPlanResult {
  dataset_id: number;
  requested: number;
  updated: number;
  train: number;
  val: number;
  test: number;
  unassigned: number;
  stratify_by_tags: boolean;
  include_test: boolean;
  seed: number;
  warnings: string[];
}

export interface MissingSampleRepairRequest {
  root_path: string;
  update_dataset_root: boolean;
}

export interface MissingSampleRepairResult {
  dataset_id: number;
  root_path: string;
  checked: number;
  repaired: number;
  skipped: number;
  errors: string[];
}
