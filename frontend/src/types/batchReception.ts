import type { FrozenPlan } from "./industrial";
import type { NormalizedRoi } from "./validation";

export interface ReceptionFilenameRule {
  delimiter: "_" | "-" | " ";
  keep_segments: number;
  include_parent: boolean;
}

export interface ReceptionProfile {
  name: string;
  import_format: "auto" | "folder" | "mvtec_ad" | "visa";
  filename_rule: ReceptionFilenameRule | null;
  category_rules: Array<{ directory: string; category_id: number }>;
}

export interface ReceptionProfileRead {
  dataset_revision: number;
  saved: boolean;
  profile: ReceptionProfile;
  context: {
    policy_version: number;
    split_ok: boolean;
    ng_grouping: string;
    roi: NormalizedRoi | null;
  };
}

export interface ReceptionPreviewRow {
  sample_id: number;
  relative_path: string;
  before_category_id: number | null;
  category_id: number | null;
  before_group: string | null;
  capture_group_id: string | null;
  reason: string | null;
  changed: boolean;
}

export interface ReceptionPlan extends Omit<FrozenPlan, "rows" | "summary"> {
  rows: ReceptionPreviewRow[];
  summary: {
    batch_id: number;
    batch_name: string;
    image_count: number;
    untriaged_count: number;
    duplicate_count: number;
    unmatched_count: number;
    conflict_count: number;
    updated_count: number;
    blocked: boolean;
    blockers: string[];
  };
}

export interface ReceptionApplied {
  dataset_revision: number;
  updated_count: number;
}
