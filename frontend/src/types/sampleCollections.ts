import type { Sample } from "./dataset";

export type CollectionKind = "basket" | "reference";
export type ReferenceVerdict = "acceptable" | "unacceptable" | "uncertain";
export interface CollectionItemInput {
  sample_id: number;
  file_hash?: string;
  verdict?: ReferenceVerdict | null;
  note?: string;
}
export interface CollectionItem extends CollectionItemInput {
  file_hash: string;
  dataset_id: number;
  filename: string;
  relative_path: string;
  verdict: ReferenceVerdict | null;
  note: string;
  sample: Sample | null;
  unavailable_reason: string | null;
}
export interface SampleCollection {
  id: number;
  name: string;
  kind: CollectionKind;
  dataset_id: number | null;
  category_id: number | null;
  version: number;
  items: CollectionItem[];
  created_at: string;
  updated_at: string;
}
export interface CollectionCreate {
  name: string;
  kind: CollectionKind;
  dataset_id?: number;
  category_id?: number;
  items?: CollectionItemInput[];
}
export interface CollectionUpdate {
  expected_version: number;
  name?: string;
  items?: CollectionItemInput[];
}
