export interface Dataset {
  id: number;
  name: string;
  description: string | null;
  task_type: string | null;
  root_path: string | null;
  sample_count: number;
  created_at: string;
  updated_at: string;
}

export interface DatasetCreate {
  name: string;
  description?: string | null;
  task_type?: string | null;
  root_path?: string | null;
}

export interface Tag {
  id: number;
  name: string;
  color: string | null;
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
  split: string | null;
  notes: string | null;
  tags: Tag[];
  created_at: string;
  updated_at: string;
}

export interface SampleUpdate {
  split?: string | null;
  notes?: string | null;
  tags?: string[];
}

export interface DatasetStats {
  dataset_id: number;
  sample_count: number;
  total_size: number;
  by_file_type: Record<string, number>;
  by_extension: Record<string, number>;
  tag_counts: Record<string, number>;
}

export interface ScanResult {
  dataset_id: number;
  root_path: string;
  scanned: number;
  imported: number;
  skipped_existing: number;
  skipped_unsupported: number;
  errors: string[];
}
