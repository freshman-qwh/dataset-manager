import type { AnnotationExportSampleQuery } from "./annotationExport";
import type { FrozenPlan } from "./industrial";
import type { NormalizedRoi } from "./validation";

export type DeliveryTarget = "training_package" | "evaluation" | "exploration";

export interface DeliveryProtocol {
  sample_query?: AnnotationExportSampleQuery;
  independent_capture_declared?: boolean;
  include_borderline_evaluation?: boolean;
  normal_ratios?: number[];
  abnormal_val_percent?: number;
  preserve_existing?: boolean;
  overrides?: Record<string, string>;
  seed?: number;
}

export interface DeliveryChecklistRequest {
  target: DeliveryTarget;
  protocol?: DeliveryProtocol;
  model?: "padim" | "patchcore";
  image_size?: number;
  roi?: NormalizedRoi | null;
}

export interface ChecklistSample {
  id: number;
  relative_path: string;
}

export interface DeliveryIssue {
  key: string;
  title: string;
  severity: "blocker" | "excluded" | "notice";
  count: number;
  sample_ids: number[];
  samples: ChecklistSample[];
  action: "triage" | "groups" | "scope" | "collect" | "review";
  guidance: string;
}

export interface ChecklistCoverageRow {
  id: number | null;
  name: string;
  total: number;
  normal: number;
  abnormal: number;
  pending: number;
  normal_groups: number;
  abnormal_groups: number;
}

export interface DeliveryChecklist {
  target: DeliveryTarget;
  dataset_revision: number;
  ready: boolean;
  plan: FrozenPlan;
  issues: DeliveryIssue[];
  coverage: {
    categories: ChecklistCoverageRow[];
    batches: ChecklistCoverageRow[];
    defects: Array<{ id: number; name: string; total: number; groups: number }>;
  };
  notes: string[];
}
