export type AnnotationExportFormat =
  | "labelme"
  | "coco_detection"
  | "coco_segmentation"
  | "yolo_detection"
  | "yolo_segmentation"
  | "voc";

export interface AnnotationExportSampleQuery {
  search?: string;
  file_type?: string;
  file_status?: string;
  tag?: string;
  split?: string;
  review_status?: string;
  sample_ids?: number[];
  sort_by?: string;
  sort_order?: "asc" | "desc";
}

export interface AnnotationExportPrecheckRequest {
  format: AnnotationExportFormat;
  sample_query: AnnotationExportSampleQuery;
  include_empty: boolean;
}

export interface AnnotationClassMapItem {
  name: string;
  id: number;
  coco_id: number;
  yolo_id: number;
}

export interface AnnotationExportIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  sample_id?: number | null;
  sample_path?: string | null;
  annotation_id?: number | null;
}

export interface AnnotationExportPrecheckResponse {
  dataset_id: number;
  format: AnnotationExportFormat;
  sample_count: number;
  annotated_sample_count: number;
  exportable_object_count: number;
  skipped_object_count: number;
  class_map: AnnotationClassMapItem[];
  issues: AnnotationExportIssue[];
  error_count: number;
  warning_count: number;
  info_count: number;
  truncated_issue_count: number;
  blocked: boolean;
}

export interface AnnotationExportDownload {
  blob: Blob;
  filename: string;
}

export interface AnnotationExportJobCreateRequest {
  format: "labelme" | "coco_detection" | "coco_segmentation";
  sample_query: AnnotationExportSampleQuery;
  include_empty: boolean;
}
