import axios from "axios";

import { API_BASE_URL } from "./client";
import type { WorkpieceViews } from "../types/workpiece";

export async function getWorkpieceViews(sampleId: number, page: number, signal?: AbortSignal): Promise<WorkpieceViews> {
  const { data } = await axios.get<WorkpieceViews>(`${API_BASE_URL}/samples/${sampleId}/workpiece-views`, {
    params: { page, page_size: 12 }, signal, timeout: 30000
  });
  return data;
}
