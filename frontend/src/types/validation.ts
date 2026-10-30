import type { Job } from "./job";

export interface ValidationRuntime {
  ready: boolean; python_path: string | null; message: string;
  versions: Record<string, string>; base_python: string | null; install_job: Job | null;
}

export interface ValidationRun {
  id: string; dataset_id: number; dataset_revision: number; name: string;
  mode: "evaluation" | "exploration" | "batch";
  recipe: {model: "padim" | "patchcore"; image_size: number; roi: NormalizedRoi | null; [key: string]: unknown};
  parent_run_id: string | null; job: Job | null; created_at: string;
  current_dataset_revision: number; summary: Record<string, unknown> | null;
}

export interface NormalizedRoi {x: number; y: number; width: number; height: number}
