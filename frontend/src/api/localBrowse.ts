import axios from "axios";

import { API_BASE_URL } from "./client";
import type { LocalBrowseQuery, LocalBrowseResponse } from "../types/localBrowse";

export async function browseLocalDataset(datasetId: number, query: LocalBrowseQuery, signal?: AbortSignal): Promise<LocalBrowseResponse> {
  const { data } = await axios.get<LocalBrowseResponse>(`${API_BASE_URL}/datasets/${datasetId}/browse`, {
    params: query,
    signal,
    timeout: 30000
  });
  return data;
}
