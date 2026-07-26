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
