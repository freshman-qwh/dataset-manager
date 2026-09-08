export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface Job {
  id: number;
  job_type: string;
  title: string;
  status: JobStatus;
  dataset_id: number | null;
  stage: string;
  progress_current: number;
  progress_total: number | null;
  error_count: number;
  attempt: number;
  parameters: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  retry_of_id: number | null;
  cancel_requested_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface JobListResponse {
  items: Job[];
  total: number;
}

export interface ScanJobCreateResponse {
  job: Job;
  created: boolean;
}

export interface AnnotationExportJobCreateResponse {
  job: Job;
  created: boolean;
}

export interface MetadataImportJobCreateResponse {
  job: Job;
  created: boolean;
}

export interface MetadataImportRollbackJobCreateResponse {
  job: Job;
  created: boolean;
}

export interface LabelmeImportJobCreateResponse {
  job: Job;
  created: boolean;
}

export interface LabelmeImportRollbackJobCreateResponse {
  job: Job;
  created: boolean;
}

export interface ThumbnailJobCreateResponse {
  job: Job | null;
  created: boolean;
  requested_count: number;
  eligible_count: number;
  cached_count: number;
  skipped_count: number;
}

export interface ThumbnailMaintenanceJobCreateResponse {
  job: Job | null;
  created: boolean;
  due: boolean;
}

export interface DatabaseBackupJobCreateResponse {
  job: Job;
  created: boolean;
}
