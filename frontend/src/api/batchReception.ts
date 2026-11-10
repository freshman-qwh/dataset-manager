import axios from "axios";

import { API_BASE_URL } from "./client";
import type { ReceptionApplied, ReceptionPlan, ReceptionProfile, ReceptionProfileRead } from "../types/batchReception";

const receptionClient = axios.create({ baseURL: API_BASE_URL, timeout: 180000 });

export async function getReceptionProfile(datasetId: number, signal?: AbortSignal): Promise<ReceptionProfileRead> {
  return (await receptionClient.get<ReceptionProfileRead>(`/datasets/${datasetId}/batch-reception/profile`, { signal })).data;
}

export async function saveReceptionProfile(datasetId: number, expectedRevision: number, profile: ReceptionProfile, signal?: AbortSignal): Promise<ReceptionProfileRead> {
  return (await receptionClient.put<ReceptionProfileRead>(`/datasets/${datasetId}/batch-reception/profile`, {
    expected_revision: expectedRevision, profile
  }, { signal })).data;
}

export async function previewBatchReception(datasetId: number, batchId: number, expectedRevision: number, signal?: AbortSignal): Promise<ReceptionPlan> {
  return (await receptionClient.post<ReceptionPlan>(`/datasets/${datasetId}/batch-reception/previews`, {
    batch_id: batchId, expected_revision: expectedRevision
  }, { signal })).data;
}

export async function getReceptionPlan(datasetId: number, planId: string, page: number, signal?: AbortSignal): Promise<ReceptionPlan> {
  return (await receptionClient.get<ReceptionPlan>(`/datasets/${datasetId}/industrial/plans/${planId}`, {
    params: { page }, signal
  })).data;
}

export async function confirmBatchReception(datasetId: number, plan: ReceptionPlan, confirmation: string, signal?: AbortSignal): Promise<ReceptionApplied> {
  return (await receptionClient.post<ReceptionApplied>(`/datasets/${datasetId}/batch-reception/previews/${plan.plan_id}/confirm`, {
    plan_hash: plan.plan_hash, confirmation
  }, { signal })).data;
}
