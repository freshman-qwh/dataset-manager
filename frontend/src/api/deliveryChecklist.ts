import axios from "axios";

import { API_BASE_URL } from "./client";
import type { DeliveryChecklist, DeliveryChecklistRequest } from "../types/deliveryChecklist";

export async function createDeliveryChecklist(datasetId: number, payload: DeliveryChecklistRequest, signal?: AbortSignal): Promise<DeliveryChecklist> {
  return (await axios.post<DeliveryChecklist>(`${API_BASE_URL}/datasets/${datasetId}/delivery-checklist`, payload, {
    signal, timeout: 180000
  })).data;
}
