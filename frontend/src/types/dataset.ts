import type {
  AnnotationClassMapItem,
  AnnotationExportFormat,
  AnnotationExportSampleQuery
} from "./annotationExport";

export type DatasetTaskType = "detection" | "segmentation" | "classification";
export type AnnotationProgress = "not_started" | "in_progress" | "completed_empty" | "completed_with_objects";
export type ReviewStatus = "not_reviewed" | "in_review" | "approved" | "rejected";
export type AnnotationQueueScope = "all_pending" | "current_filter" | "current_split";

export interface DatasetTaskCapabilities {
  label: string;
  annotation_mode: "geometry" | "sample_tags" | "unsupported" | string;
  allowed_shape_types: AnnotationShapeType[];
  default_export_format: string;
  supported: boolean;
  unsupported_reason: string | null;
}

export interface Dataset {
  id: number;
  name: string;
  description: string | null;
  task_type: DatasetTaskType | string;
  task_capabilities: DatasetTaskCapabilities;
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
  task_type?: DatasetTaskType;
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

export interface AnnotationClass {
  id: number;
  dataset_id: number;
  name: string;
  color: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnnotationClassCreate {
  name: string;
  color?: string | null;
  description?: string | null;
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
  annotation_progress: AnnotationProgress;
  review_status: ReviewStatus;
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
  thumbnail_prefetch_sample_ids: number[];
}

export interface SampleNavigationResponse {
  current_sample: Sample | null;
  previous_sample: Sample | null;
  next_sample: Sample | null;
  current_index: number | null;
  total: number;
  remaining: number;
  queue_scope: AnnotationQueueScope;
  sort_by: string;
  sort_order: "asc" | "desc" | string;
}

export interface SampleUpdate {
  split?: string | null;
  annotation_progress?: AnnotationProgress;
  review_status?: ReviewStatus;
  notes?: string | null;
  tags?: string[];
}

export interface BatchSampleUpdate {
  sample_ids: number[];
  split?: string | null;
  annotation_progress?: AnnotationProgress;
  review_status?: ReviewStatus;
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

export type AnnotationShapeType = "rectangle" | "polygon" | "point" | "points";

export interface AnnotationObject {
  id?: number;
  sample_id?: number;
  dataset_id?: number;
  client_id: string;
  label: string;
  class_id: number | null;
  shape_type: AnnotationShapeType;
  points: number[];
  flags: Record<string, boolean>;
  attributes: Record<string, unknown>;
  group_id: number | null;
  z_order: number;
  locked: boolean;
  hidden: boolean;
  source: "manual" | "file" | "auto" | string;
  notes: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AnnotationReplaceItem {
  label: string;
  class_id?: number | null;
  shape_type: AnnotationShapeType;
  points: number[];
  flags?: Record<string, boolean>;
  attributes?: Record<string, unknown>;
  group_id?: number | null;
  z_order?: number;
  locked?: boolean;
  hidden?: boolean;
  source?: string;
  notes?: string | null;
}

export interface AnnotationReplaceRequest {
  annotations: AnnotationReplaceItem[];
  review_status?: string | null;
  save_mode?: "draft" | "complete" | "confirm_empty";
}

export interface AnnotationTagSyncResult {
  sample_id: number;
  source: "annotation_classes";
  added_tags: string[];
  existing_tags: string[];
}

export interface DatasetStats {
  dataset_id: number;
  sample_count: number;
  total_size: number;
  by_file_type: Record<string, number>;
  by_extension: Record<string, number>;
  by_status: Record<string, number>;
  by_split: Record<string, number>;
  by_annotation_progress: Record<AnnotationProgress | string, number>;
  by_review_status: Record<string, number>;
  tag_counts: Record<string, number>;
  duplicate_groups: number;
  duplicate_samples: number;
  untagged_samples: number;
  samples_with_objects: number;
  annotation_count: number;
  by_annotation_label: Record<string, number>;
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
  hashed: number;
  hash_skipped_unchanged: number;
  batches_committed: number;
  error_count: number;
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
  annotationProgress?: AnnotationProgress;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  thumbnailPrefetch?: number;
}

export type QualityIssueSeverity = "error" | "warning" | "info";

export interface QualityIssue {
  severity: QualityIssueSeverity;
  code: string;
  title: string;
  message: string;
  sample_id: number | null;
  sample_path: string | null;
  annotation_id: number | null;
  related_sample_ids: number[];
  related_annotation_ids: number[];
}

export interface DatasetQualityReport {
  dataset_id: number;
  generated_at: string;
  sample_count: number;
  image_sample_count: number;
  samples_with_objects_count: number;
  confirmed_empty_sample_count: number;
  annotation_progress_counts: Record<AnnotationProgress | string, number>;
  annotation_count: number;
  issue_count: number;
  error_count: number;
  warning_count: number;
  info_count: number;
  truncated_issue_count: number;
  check_counts: Record<string, number>;
  review_status_counts: Record<string, number>;
  class_counts: Record<string, number>;
  split_class_counts: Record<string, Record<string, number>>;
  issues: QualityIssue[];
}

export type TrainingReadinessStatus = "blocked" | "needs_attention" | "ready";
export type TrainingReadinessScope = "filtered" | "all" | "split" | "selected";
export type TrainingReadinessExportFormat = AnnotationExportFormat | "csv" | "manifest";

export interface TrainingReadinessConfigInput {
  format: TrainingReadinessExportFormat;
  scope: TrainingReadinessScope;
  split?: string | null;
  include_empty: boolean;
  sample_query: AnnotationExportSampleQuery;
  class_map: AnnotationClassMapItem[];
}

export interface TrainingReadinessConfig extends TrainingReadinessConfigInput {
  task_type: string;
  saved_at: string;
  last_export_at: string | null;
}

export interface TrainingReadinessReport {
  dataset_id: number;
  generated_at: string;
  task_type: string;
  task_label: string;
  status: TrainingReadinessStatus;
  recommended_export_format: string;
  compatible_export_formats: string[];
  advanced_export_formats: string[];
  scoped_sample_count: number;
  completed_sample_count: number;
  confirmed_empty_sample_count: number;
  pending_sample_count: number;
  pending_review_count: number;
  rejected_sample_count: number;
  blocking_issue_count: number;
  suggested_fix_count: number;
  notice_count: number;
  truncated_issue_count?: number;
  issues?: QualityIssue[];
  split_counts: Record<string, number>;
  split_covered_sample_count: number;
  split_coverage_percent: number;
  last_export_at: string | null;
  last_config: TrainingReadinessConfig | null;
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
  dry_run?: boolean;
  expected_source_sha256?: string;
}

export interface MetadataImportJobCreateRequest {
  file_path: string;
  match_by: string;
  tag_column: string;
  replace_tags: boolean;
  expected_source_sha256: string;
}

export interface MetadataImportIssue {
  severity: "warning" | "error";
  code: string;
  message: string;
  row_number: number | null;
  match_value: string | null;
}

export interface MetadataImportResult {
  dataset_id: number;
  source_path: string;
  source_size_bytes: number;
  source_sha256: string;
  dry_run: boolean;
  total_rows: number;
  matched: number;
  planned_updates: number;
  updated: number;
  skipped: number;
  error_count: number;
  issues: MetadataImportIssue[];
  errors: string[];
}

export type LabelmeImportMode = "file" | "directory";
export type LabelmeImportStrategy = "replace" | "append";

export interface LabelmeImportRequest {
  path: string;
  mode: LabelmeImportMode;
  sample_id?: number;
  strategy: LabelmeImportStrategy;
  dry_run?: boolean;
  sync_sample_tags: boolean;
  expected_source_sha256?: string;
  expected_plan_fingerprint?: string;
}

export interface LabelmeImportJobCreateRequest {
  path: string;
  mode: LabelmeImportMode;
  sample_id?: number;
  strategy: LabelmeImportStrategy;
  sync_sample_tags: boolean;
  expected_source_sha256: string;
  expected_plan_fingerprint: string;
}

export interface LabelmeImportIssue {
  severity: "warning" | "error";
  code: string;
  message: string;
  file_path: string | null;
  sample_id: number | null;
  sample_path: string | null;
}

export interface LabelmeImportResult {
  dataset_id: number;
  source_path: string;
  mode: LabelmeImportMode;
  strategy: LabelmeImportStrategy;
  dry_run: boolean;
  source_size_bytes: number;
  source_sha256: string;
  plan_fingerprint: string;
  checked_files: number;
  matched_files: number;
  imported_samples: number;
  created_annotations: number;
  skipped_shapes: number;
  warnings: LabelmeImportIssue[];
  errors: LabelmeImportIssue[];
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
