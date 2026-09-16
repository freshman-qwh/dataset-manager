import type { AnnotationClassMapItem, AnnotationExportSampleQuery } from "./annotationExport";

export type DatasetSnapshotExportFormat =
  | "labelme"
  | "coco_detection"
  | "coco_segmentation"
  | "yolo_detection"
  | "yolo_segmentation"
  | "voc"
  | "csv"
  | "manifest";

export interface DatasetSnapshotExportConfig {
  format: DatasetSnapshotExportFormat;
  include_empty: boolean;
  class_map: AnnotationClassMapItem[];
}

export interface DatasetSnapshotCreate {
  name?: string | null;
  sample_query: AnnotationExportSampleQuery;
  export_config: DatasetSnapshotExportConfig;
}

export interface DatasetSnapshot {
  id: number;
  dataset_id: number;
  dataset_revision: number;
  name: string | null;
  content_sha256: string;
  sample_count: number;
  annotation_count: number;
  class_count: number;
  sample_query: AnnotationExportSampleQuery;
  export_config: DatasetSnapshotExportConfig;
  created_at: string;
}

export interface DatasetSnapshotDocument {
  snapshot_id: number;
  dataset_id: number;
  dataset_revision: number;
  created_at: string;
  content_sha256: string;
  content: {
    schema_version: 1;
    dataset: Record<string, unknown>;
    sample_query: AnnotationExportSampleQuery;
    export_config: DatasetSnapshotExportConfig;
    class_map: AnnotationClassMapItem[];
    tag_catalog: Array<Record<string, unknown>>;
    annotation_class_catalog: Array<Record<string, unknown>>;
    sample_count: number;
    annotation_count: number;
    samples: Array<Record<string, unknown>>;
  };
}

export type DatasetSnapshotChangeType =
  | "added"
  | "removed"
  | "file"
  | "metadata"
  | "tags"
  | "split"
  | "annotations";

export interface DatasetSnapshotDiffItem {
  sample_id: number;
  relative_path: string;
  change_types: DatasetSnapshotChangeType[];
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface DatasetSnapshotDiffResponse {
  dataset_id: number;
  base_snapshot_id: number;
  target_snapshot_id: number;
  base_revision: number;
  target_revision: number;
  summary: {
    added: number;
    removed: number;
    file_changed: number;
    metadata_changed: number;
    tags_changed: number;
    split_changed: number;
    annotations_changed: number;
    changed_samples: number;
  };
  total: number;
  page: number;
  page_size: number;
  items: DatasetSnapshotDiffItem[];
}

export interface DatasetSnapshotTrainingLabels {
  schema_version: 1;
  snapshot_id: number;
  dataset_id: number;
  dataset_revision: number;
  snapshot_content_sha256: string;
  format: DatasetSnapshotExportFormat;
  include_empty: boolean;
  class_map: AnnotationClassMapItem[];
  sample_count: number;
  label_sha256: string;
  labels: Array<Record<string, unknown>>;
}
