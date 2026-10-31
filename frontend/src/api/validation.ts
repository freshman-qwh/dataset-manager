import axios from "axios";
import type { FrozenPlan } from "../types/industrial";
import type { Job } from "../types/job";
import type { ValidationRuntime, ValidationRun } from "../types/validation";
import type { ValidationResults, ValidationPredictions, ValidationDecision } from "../types/validation";
import type { ValidationReviewSummary } from "../types/validation";
import type { ValidationPreparation,NormalizedRoi,QualityInspection } from "../types/validation";

const api = axios.create({baseURL: "/api", timeout: 180000});

export const getValidationRuntime = async () => (await api.get<ValidationRuntime>("/validation/runtime")).data;
export const setValidationRuntime = async (python_path: string) => (await api.put<ValidationRuntime>("/validation/runtime", {python_path})).data;
export const installValidationRuntime = async (base_python?: string) => (await api.post<Job>("/validation/runtime/install-jobs", {base_python})).data;
export const previewValidation = async (datasetId: number, payload: Record<string, unknown>) => (await api.post<FrozenPlan>(`/datasets/${datasetId}/validation/previews`, payload)).data;
export const createValidationRun = async (datasetId: number, plan: FrozenPlan, name: string) => (await api.post<ValidationRun>(`/datasets/${datasetId}/validation/runs`, {plan_id:plan.plan_id, plan_hash:plan.plan_hash, name})).data;
export const listValidationRuns = async (datasetId: number) => (await api.get<ValidationRun[]>(`/datasets/${datasetId}/validation/runs`)).data;
export const getValidationRun = async (runId: string) => (await api.get<ValidationRun>(`/validation/runs/${runId}`)).data;
export const getValidationResults = async (runId:string, threshold?:number, signal?:AbortSignal) => (await api.get<ValidationResults>(`/validation/runs/${runId}/results`,{params:{threshold},signal})).data;
export const getValidationPredictions = async (runId:string, params:Record<string,string|number|undefined>, signal?:AbortSignal) => (await api.get<ValidationPredictions>(`/validation/runs/${runId}/predictions`,{params,signal})).data;
export const freezeValidationThreshold = async (runId:string,threshold:number) => (await api.post<ValidationDecision>(`/validation/runs/${runId}/freeze-threshold`,{threshold})).data;
export const validationImageUrl = (runId:string,sampleId:number,kind="preview") => `/api/validation/runs/${runId}/images/${sampleId}?kind=${kind}`;
export const getValidationReview = async (runId:string) => (await api.get<ValidationReviewSummary>(`/validation/runs/${runId}/review`)).data;
export const addValidationReview = async (runId:string,sample_ids:number[]) => (await api.post<ValidationReviewSummary>(`/validation/runs/${runId}/review`,{sample_ids})).data;
export const updateValidationReview = async (runId:string,sampleId:number,payload:Record<string,unknown>) => (await api.patch<ValidationReviewSummary>(`/validation/runs/${runId}/review/${sampleId}`,payload)).data;
export const previewValidationBatch = async (runId:string,payload:Record<string,unknown>) => (await api.post<FrozenPlan>(`/validation/runs/${runId}/batch-previews`,payload)).data;
export const getValidationPreparation = async (id:number) => (await api.get<ValidationPreparation>(`/datasets/${id}/validation/settings`)).data;
export const saveValidationRoi = async (id:number,roi:NormalizedRoi|null,expected_dataset_revision:number) => (await api.put<ValidationPreparation>(`/datasets/${id}/validation/settings`,{roi,expected_dataset_revision})).data;
export const inspectValidationQuality = async (id:number,payload:Record<string,unknown>) => (await api.post<QualityInspection>(`/datasets/${id}/validation/quality-inspections`,payload)).data;

export function validationError(error: unknown): string {
  const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(item => String(item.msg ?? "请检查填写的参数")).join("；");
  return "请求未完成，请检查本地服务后重试。";
}

export const deleteValidationRun = async (runId:string) => {await api.delete(`/validation/runs/${runId}`);};
