import axios from "axios";
import { API_BASE_URL } from "./client";
import type { CollectionCreate, CollectionKind, CollectionUpdate, SampleCollection } from "../types/sampleCollections";

const client = axios.create({ baseURL: `${API_BASE_URL}/sample-collections`, timeout: 30000 });

export async function listSampleCollections(query: { kind?: CollectionKind; dataset_id?: number; category_id?: number } = {}, signal?: AbortSignal): Promise<SampleCollection[]> {
  return (await client.get<SampleCollection[]>("", { params: query, signal })).data;
}
export async function createSampleCollection(payload: CollectionCreate): Promise<SampleCollection> {
  return (await client.post<SampleCollection>("", payload)).data;
}
export async function getSampleCollection(id: number, signal?: AbortSignal): Promise<SampleCollection> {
  return (await client.get<SampleCollection>(`/${id}`, { signal })).data;
}
export async function updateSampleCollection(id: number, payload: CollectionUpdate): Promise<SampleCollection> {
  return (await client.patch<SampleCollection>(`/${id}`, payload)).data;
}
export async function deleteSampleCollection(id: number, expectedVersion: number): Promise<void> {
  await client.delete(`/${id}`, { params: { expected_version: expectedVersion } });
}
