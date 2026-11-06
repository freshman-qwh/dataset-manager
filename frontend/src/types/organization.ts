export interface Project {
  id: number;
  name: string;
  description: string | null;
  dataset_count?: number;
  created_at: string;
  updated_at: string;
}

export interface DatasetCategory {
  id: number;
  dataset_id: number;
  name: string;
  description: string | null;
  sample_count: number;
  normal_count?: number;
  anomaly_count?: number;
  cover_sample_id?: number | null;
  cover_file_hash?: string | null;
}

export interface DatasetBatch {
  id: number;
  dataset_id: number;
  name: string;
  code: string;
  captured_at: string | null;
  notes: string | null;
  sample_count: number;
}

export interface DatasetOrganization {
  project: Project | null;
  categories: DatasetCategory[];
  batches: DatasetBatch[];
}

export interface ScanOptions {
  recognize_existing?: boolean;
  batch_id?: number | null;
  new_batch_name?: string | null;
  import_format?: "auto" | "folder" | "mvtec_ad" | "visa";
}

export interface ImportPreview {
  detected_format: string;
  categories: string[];
  image_count: number;
  mask_count: number;
  warnings: string[];
  official_split_counts: Record<string, number>;
}
