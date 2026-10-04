export interface SamPoint { x: number; y: number; label: 0 | 1 }
export interface SamPrompts { points: SamPoint[]; box: number[] | null }
export interface SamStatus {
  ready: boolean;
  model: "sam_vit_b";
  loaded: boolean;
  device: string | null;
  message: string;
}
export interface SamPrediction {
  sample_id: number;
  model: "sam_vit_b";
  polygons: number[][];
  score: number;
  image_width: number;
  image_height: number;
  elapsed_ms: number;
  device: string;
  warnings: string[];
}
