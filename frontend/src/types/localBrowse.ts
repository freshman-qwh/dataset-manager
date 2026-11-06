import type { Sample } from "./dataset";

export interface BrowseFolder {
  name: string;
  path: string;
  sample_count: number;
  image_count: number;
  cover_sample_id: number | null;
  cover_file_hash: string | null;
}

export interface LocalBrowseResponse {
  dataset_id: number;
  folder: string;
  recursive: boolean;
  source_root: string;
  sources: { path: string; sample_count: number; image_count: number }[];
  folders: BrowseFolder[];
  folders_total: number;
  folder_page: number;
  folder_page_size: number;
  items: Sample[];
  total: number;
  page: number;
  page_size: number;
}

export interface LocalBrowseQuery {
  category_id?: number;
  batch_id?: number;
  all_sources?: boolean;
  folder: string;
  recursive: boolean;
  search: string;
  file_type: string;
  page: number;
  page_size: number;
  folder_page: number;
  folder_page_size: number;
  source_root?: string;
}
