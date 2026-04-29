import axios from "axios";

import type {
  Dataset,
  DatasetCreate,
  DatasetStats,
  Sample,
  SampleUpdate,
  ScanResult
} from "../types/dataset";

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000/api";

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000
});

export async function listDatasets(): Promise<Dataset[]> {
  const { data } = await client.get<Dataset[]>("/datasets");
  return data;
}

export async function createDataset(payload: DatasetCreate): Promise<Dataset> {
  const { data } = await client.post<Dataset>("/datasets", payload);
  return data;
}

export async function getDataset(datasetId: number): Promise<Dataset> {
  const { data } = await client.get<Dataset>(`/datasets/${datasetId}`);
  return data;
}

export async function scanDataset(datasetId: number, folderPath: string): Promise<ScanResult> {
  const { data } = await client.post<ScanResult>(`/datasets/${datasetId}/scan`, {
    folder_path: folderPath
  });
  return data;
}

export async function listSamples(params: {
  datasetId: number;
  search?: string;
  fileType?: string;
  tag?: string;
}): Promise<Sample[]> {
  const { datasetId, search, fileType, tag } = params;
  const { data } = await client.get<Sample[]>(`/datasets/${datasetId}/samples`, {
    params: {
      search: search || undefined,
      file_type: fileType || undefined,
      tag: tag || undefined
    }
  });
  return data;
}

export async function getSample(sampleId: number): Promise<Sample> {
  const { data } = await client.get<Sample>(`/samples/${sampleId}`);
  return data;
}

export async function updateSample(sampleId: number, payload: SampleUpdate): Promise<Sample> {
  const { data } = await client.patch<Sample>(`/samples/${sampleId}`, payload);
  return data;
}

export async function getDatasetStats(datasetId: number): Promise<DatasetStats> {
  const { data } = await client.get<DatasetStats>(`/stats/datasets/${datasetId}`);
  return data;
}

export function getSampleFileUrl(sampleId: number): string {
  return `${API_BASE_URL}/samples/${sampleId}/file`;
}

export function getManifestUrl(datasetId: number): string {
  return `${API_BASE_URL}/datasets/${datasetId}/export-manifest`;
}
