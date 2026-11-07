import axios from "axios";
import { API_BASE_URL } from "./client";
import type { TriageNavigation, TriageQueueScope, TriageStatus } from "../types/triage";

export interface WorkScopeQuery {
  queue_scope: TriageQueueScope;
  sample_id?: number;
  search?: string;
  split?: string;
  triage_status?: string;
  ok_grade?: string;
  defect_severity?: string;
  defect_type_id?: number;
}

export interface WorkSampleState {
  sample_id: number;
  triage_version: number;
  file_hash: string;
  triage_policy_version: number | null;
  triage_status: TriageStatus;
  triage_outdated: boolean;
  file_status?: string;
}

export async function getWorkScope(datasetId: number, query: WorkScopeQuery) {
  const { data } = await axios.post<{ sample_ids: number[]; dataset_revision: number }>(`${API_BASE_URL}/datasets/${datasetId}/triage/work-scope`, query, { timeout: 30000 });
  return data;
}

export async function getWorkNavigation(datasetId: number, sampleIds: number[], sampleId?: number | null, targetIndex?: number): Promise<TriageNavigation> {
  const { data } = await axios.post<TriageNavigation>(`${API_BASE_URL}/datasets/${datasetId}/triage/work-navigation`, {
    sample_ids: sampleIds, sample_id: sampleId || undefined, target_index: targetIndex
  }, { timeout: 30000 });
  return data;
}

export async function getWorkState(datasetId: number, sampleIds: number[]) {
  const { data } = await axios.post<{ items: WorkSampleState[]; dataset_revision: number }>(`${API_BASE_URL}/datasets/${datasetId}/triage/work-state`, { sample_ids: sampleIds }, { timeout: 30000 });
  return data;
}
