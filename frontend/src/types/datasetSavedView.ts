import type {
  AnnotationProgress,
  AnnotationQueueScope,
  DatasetTaskType,
  ReviewStatus
} from "./dataset";

export type DatasetSavedViewSortField =
  | "created_at"
  | "updated_at"
  | "filename"
  | "relative_path"
  | "file_size"
  | "extension"
  | "file_type"
  | "file_status"
  | "split"
  | "review_status"
  | "annotation_progress";

export interface DatasetSavedViewQuery {
  search?: string;
  file_type?: string;
  file_status?: string;
  tag?: string;
  split?: string;
  review_status?: ReviewStatus;
  annotation_progress?: AnnotationProgress;
  sort_by: DatasetSavedViewSortField;
  sort_order: "asc" | "desc";
}

export interface DatasetSavedViewCreate {
  name: string;
  queue_scope: AnnotationQueueScope;
  sample_query: DatasetSavedViewQuery;
}

export interface DatasetSavedView {
  id: number;
  dataset_id: number;
  name: string;
  task_type: DatasetTaskType | string;
  queue_scope: AnnotationQueueScope;
  sample_query: DatasetSavedViewQuery;
  created_at: string;
  updated_at: string;
}
