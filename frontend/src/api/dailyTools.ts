import axios from "axios";

import { API_BASE_URL } from "./client";
import type { CoverageRead, CoverageSamplesRead, CoverageStatus, FilenameLookupRead, FilenameLookupResult } from "../types/dailyTools";

export async function lookupFilenames(datasetId: number, entries: string[], signal?: AbortSignal): Promise<FilenameLookupRead> {
  const { data } = await axios.post<FilenameLookupRead>(`${API_BASE_URL}/datasets/${datasetId}/filename-lookup`, { entries }, { signal, timeout: 30000 });
  return data;
}
export async function getLookupCandidates(datasetId: number, entry: string, page: number, signal?: AbortSignal): Promise<FilenameLookupResult> {
  const { data } = await axios.get<FilenameLookupResult>(`${API_BASE_URL}/datasets/${datasetId}/filename-lookup/candidates`, { params: { entry, page }, signal, timeout: 30000 });
  return data;
}
export async function getCoverage(datasetId: number, signal?: AbortSignal): Promise<CoverageRead> {
  const { data } = await axios.get<CoverageRead>(`${API_BASE_URL}/datasets/${datasetId}/coverage`, { signal, timeout: 30000 });
  return data;
}
export async function getCoverageSamples(datasetId: number, query: { category_id: number | null; batch_id: number | null; status: CoverageStatus; page: number }, signal?: AbortSignal): Promise<CoverageSamplesRead> {
  const { data } = await axios.get<CoverageSamplesRead>(`${API_BASE_URL}/datasets/${datasetId}/coverage/samples`, { params: query, signal, timeout: 30000 });
  return data;
}
