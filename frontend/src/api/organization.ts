import axios from "axios";
import { API_BASE_URL } from "./client";
import type { DatasetBatch, DatasetCategory, DatasetOrganization, ImportPreview, Project, ScanOptions } from "../types/organization";

const organizationClient = axios.create({ baseURL: API_BASE_URL, timeout: 120000 });

export async function listProjects(signal?: AbortSignal): Promise<Project[]> { return (await organizationClient.get<Project[]>("/projects", { signal })).data; }
export async function createProject(payload: { name: string; description?: string | null }): Promise<Project> { return (await organizationClient.post<Project>("/projects", payload)).data; }
export async function updateProject(id: number, payload: { name: string; description?: string | null }): Promise<Project> { return (await organizationClient.patch<Project>(`/projects/${id}`, payload)).data; }
export async function deleteProject(id: number): Promise<void> { await organizationClient.delete(`/projects/${id}`); }
export async function getOrganization(datasetId: number, signal?: AbortSignal): Promise<DatasetOrganization> { return (await organizationClient.get<DatasetOrganization>(`/datasets/${datasetId}/organization`, { signal })).data; }
export async function createCategory(datasetId: number, payload: { name: string; description?: string | null }): Promise<DatasetCategory> { return (await organizationClient.post<DatasetCategory>(`/datasets/${datasetId}/categories`, payload)).data; }
export async function updateCategory(datasetId: number, id: number, payload: { name: string; description?: string | null }): Promise<DatasetCategory> { return (await organizationClient.patch<DatasetCategory>(`/datasets/${datasetId}/categories/${id}`, payload)).data; }
export async function deleteCategory(datasetId: number, id: number): Promise<void> { await organizationClient.delete(`/datasets/${datasetId}/categories/${id}`); }
export async function createBatch(datasetId: number, payload: { name: string; captured_at?: string | null; notes?: string | null }): Promise<DatasetBatch> { return (await organizationClient.post<DatasetBatch>(`/datasets/${datasetId}/batches`, payload)).data; }
export async function updateBatch(datasetId: number, id: number, payload: { name: string; captured_at?: string | null; notes?: string | null }): Promise<DatasetBatch> { return (await organizationClient.patch<DatasetBatch>(`/datasets/${datasetId}/batches/${id}`, payload)).data; }
export async function deleteBatch(datasetId: number, id: number): Promise<void> { await organizationClient.delete(`/datasets/${datasetId}/batches/${id}`); }
export async function assignOrganization(datasetId: number, payload: { sample_ids: number[]; category_id?: number | null; batch_id?: number | null }): Promise<void> { await organizationClient.patch(`/datasets/${datasetId}/organization/assign`, payload); }
export async function previewImport(datasetId: number, path: string, options: ScanOptions, signal?: AbortSignal): Promise<ImportPreview> { return (await organizationClient.post<ImportPreview>(`/datasets/${datasetId}/import-preview`, { folder_path: path, ...options }, { signal })).data; }

export async function resolveProjectChoice(choice: string, newName: string): Promise<number | null> {
  if (!choice) return null;
  if (choice !== "new") return Number(choice);
  const name = newName.trim();
  if (!name) throw new Error("请填写新项目名称。");
  const existing = (await listProjects()).find((item) => item.name === name);
  return existing?.id ?? (await createProject({ name })).id;
}

export function organizationError(error: unknown, fallback: string): string {
  const detail: unknown = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
  return typeof detail === "string" ? detail : error instanceof Error && !axios.isAxiosError(error) ? error.message : fallback;
}
