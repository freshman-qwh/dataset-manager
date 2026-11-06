import axios from "axios";

import { API_BASE_URL } from "./client";
import type { ComparisonQuery, ComparisonRead } from "../types/comparison";

export async function getComparison(datasetId: number, query: ComparisonQuery, signal?: AbortSignal): Promise<ComparisonRead> {
  const { data } = await axios.get<ComparisonRead>(`${API_BASE_URL}/datasets/${datasetId}/comparison`, {
    params: query,
    signal,
    timeout: 30000
  });
  return data;
}
