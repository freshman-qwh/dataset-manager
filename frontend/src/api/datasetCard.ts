import axios from "axios";
import { API_BASE_URL } from "./client";
import type { DatasetCard } from "../types/datasetCard";

export async function getDatasetCard(datasetId: number, signal?: AbortSignal): Promise<DatasetCard> {
  const { data } = await axios.get<DatasetCard>(`${API_BASE_URL}/datasets/${datasetId}/card`, { signal, timeout: 30000 });
  return data;
}
