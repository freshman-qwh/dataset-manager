import axios from "axios";
import type { FrozenPlan } from "../types/industrial";
import type { Job } from "../types/job";
import type { ValidationRuntime, ValidationRun } from "../types/validation";

const api = axios.create({baseURL: "/api", timeout: 180000});

export const getValidationRuntime = async () => (await api.get<ValidationRuntime>("/validation/runtime")).data;
export const setValidationRuntime = async (python_path: string) => (await api.put<ValidationRuntime>("/validation/runtime", {python_path})).data;
export const installValidationRuntime = async (base_python?: string) => (await api.post<Job>("/validation/runtime/install-jobs", {base_python})).data;
export const previewValidation = async (datasetId: number, payload: Record<string, unknown>) => (await api.post<FrozenPlan>(`/datasets/${datasetId}/validation/previews`, payload)).data;
export const createValidationRun = async (datasetId: number, plan: FrozenPlan, name: string) => (await api.post<ValidationRun>(`/datasets/${datasetId}/validation/runs`, {plan_id:plan.plan_id, plan_hash:plan.plan_hash, name})).data;
export const listValidationRuns = async (datasetId: number) => (await api.get<ValidationRun[]>(`/datasets/${datasetId}/validation/runs`)).data;
export const getValidationRun = async (runId: string) => (await api.get<ValidationRun>(`/validation/runs/${runId}`)).data;

export function validationError(error: unknown): string {
  const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(item => String(item.msg ?? "请检查填写的参数")).join("；");
  return "请求未完成，请检查本地服务后重试。";
}
