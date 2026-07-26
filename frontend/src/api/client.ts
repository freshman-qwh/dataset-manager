import axios from "axios";

import type {
  AnnotationExportDownload,
  AnnotationExportFormat,
  AnnotationExportJobCreateRequest,
  AnnotationExportPrecheckRequest,
  AnnotationExportPrecheckResponse,
  AnnotationExportSampleQuery
} from "../types/annotationExport";
import type {
  AnnotationClass,
  AnnotationClassCreate,
  AnnotationObject,
  AnnotationQueueScope,
  AnnotationReplaceRequest,
  AnnotationTagSyncResult,
  Dataset,
  DatasetCreate,
  DatasetStats,
  DatasetQualityReport,
  DirectoryListResponse,
  DuplicateReport,
  ExportTemplateResponse,
  BatchSampleUpdate,
  BatchSampleUpdateResult,
  MissingSampleRepairRequest,
  MissingSampleRepairResult,
  MetadataImportRequest,
  MetadataImportResult,
  Sample,
  SampleDeleteResult,
  SampleListResponse,
  SampleNavigationResponse,
  SampleQuery,
  SamplePreview,
  SampleUpdate,
  ScanResult,
  SplitPlanRequest,
  SplitPlanResult,
  Tag,
  TagCreate,
  TrainingReadinessConfig,
  TrainingReadinessConfigInput,
  TrainingReadinessReport
} from "../types/dataset";
import type {
  DatabaseIntegrityReport,
  DatabaseRepairPreview,
  DatabaseRepairResult
} from "../types/system";
import type {
  AnnotationExportJobCreateResponse,
  Job,
  JobListResponse,
  ScanJobCreateResponse
} from "../types/job";

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

export async function listJobs(
  limit = 100,
  filters?: { datasetId?: number; jobType?: string }
): Promise<JobListResponse> {
  const { data } = await client.get<JobListResponse>("/jobs", {
    params: {
      limit,
      dataset_id: filters?.datasetId,
      job_type: filters?.jobType
    }
  });
  return data;
}

export async function getJob(jobId: number): Promise<Job> {
  const { data } = await client.get<Job>(`/jobs/${jobId}`);
  return data;
}

export async function cancelJob(jobId: number): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${jobId}/cancel`);
  return data;
}

export async function retryJob(jobId: number): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${jobId}/retry`);
  return data;
}

export async function getDatabaseIntegrityReport(): Promise<DatabaseIntegrityReport> {
  const { data } = await client.get<DatabaseIntegrityReport>("/system/database-integrity");
  return data;
}

export async function previewDatabaseIntegrityRepair(
  actionIds: string[]
): Promise<DatabaseRepairPreview> {
  const { data } = await client.post<DatabaseRepairPreview>(
    "/system/database-integrity/repair-preview",
    { action_ids: actionIds }
  );
  return data;
}

export async function repairDatabaseIntegrity(payload: {
  report_token: string;
  action_ids: string[];
  confirmation: string;
}): Promise<DatabaseRepairResult> {
  const { data } = await client.post<DatabaseRepairResult>(
    "/system/database-integrity/repair",
    payload
  );
  return data;
}

export async function createDataset(payload: DatasetCreate): Promise<Dataset> {
  const { data } = await client.post<Dataset>("/datasets", payload);
  return data;
}

export async function updateDataset(datasetId: number, payload: Partial<DatasetCreate>): Promise<Dataset> {
  const { data } = await client.patch<Dataset>(`/datasets/${datasetId}`, payload);
  return data;
}

export async function deleteDataset(datasetId: number): Promise<void> {
  await client.delete(`/datasets/${datasetId}`);
}

export async function getDataset(datasetId: number, signal?: AbortSignal): Promise<Dataset> {
  const { data } = await client.get<Dataset>(`/datasets/${datasetId}`, { signal });
  return data;
}

export async function listDirectories(path?: string): Promise<DirectoryListResponse> {
  const { data } = await client.get<DirectoryListResponse>("/filesystem/directories", {
    params: { path: path || undefined }
  });
  return data;
}

export async function getDuplicateReport(datasetId: number, signal?: AbortSignal): Promise<DuplicateReport> {
  const { data } = await client.get<DuplicateReport>(`/datasets/${datasetId}/duplicates`, { signal });
  return data;
}

export async function getDatasetQualityReport(datasetId: number): Promise<DatasetQualityReport> {
  const { data } = await client.get<DatasetQualityReport>(`/datasets/${datasetId}/quality-report`);
  return data;
}

export async function getTrainingReadiness(datasetId: number): Promise<TrainingReadinessReport> {
  const { data } = await client.get<TrainingReadinessReport>(`/datasets/${datasetId}/training-readiness`);
  return data;
}

export async function saveTrainingReadinessConfig(
  datasetId: number,
  payload: TrainingReadinessConfigInput
): Promise<TrainingReadinessConfig> {
  const { data } = await client.put<TrainingReadinessConfig>(
    `/datasets/${datasetId}/training-readiness/config`,
    payload
  );
  return data;
}

export async function recordTrainingExport(
  datasetId: number,
  payload: TrainingReadinessConfigInput
): Promise<TrainingReadinessConfig> {
  const { data } = await client.post<TrainingReadinessConfig>(
    `/datasets/${datasetId}/training-readiness/exports`,
    payload
  );
  return data;
}

export async function listTags(datasetId: number, signal?: AbortSignal): Promise<Tag[]> {
  const { data } = await client.get<Tag[]>(`/datasets/${datasetId}/tags`, { signal });
  return data;
}

export async function listAnnotationClasses(datasetId: number): Promise<AnnotationClass[]> {
  const { data } = await client.get<AnnotationClass[]>(`/datasets/${datasetId}/annotation-classes`);
  return data;
}

export async function createAnnotationClass(
  datasetId: number,
  payload: AnnotationClassCreate
): Promise<AnnotationClass> {
  const { data } = await client.post<AnnotationClass>(`/datasets/${datasetId}/annotation-classes`, payload);
  return data;
}

export async function createTag(datasetId: number, payload: TagCreate): Promise<Tag> {
  const { data } = await client.post<Tag>(`/datasets/${datasetId}/tags`, payload);
  return data;
}

export async function updateTag(tagId: number, payload: Partial<TagCreate>): Promise<Tag> {
  const { data } = await client.patch<Tag>(`/tags/${tagId}`, payload);
  return data;
}

export async function deleteTag(tagId: number): Promise<void> {
  await client.delete(`/tags/${tagId}`);
}

export async function importMetadata(
  datasetId: number,
  payload: MetadataImportRequest
): Promise<MetadataImportResult> {
  const { data } = await client.post<MetadataImportResult>(`/datasets/${datasetId}/import-metadata`, payload);
  return data;
}

export async function scanDataset(datasetId: number, folderPath: string): Promise<ScanResult> {
  const { data } = await client.post<ScanResult>(`/datasets/${datasetId}/scan`, {
    folder_path: folderPath
  });
  return data;
}

export async function createScanJob(
  datasetId: number,
  folderPath: string
): Promise<ScanJobCreateResponse> {
  const { data } = await client.post<ScanJobCreateResponse>(
    `/datasets/${datasetId}/scan-jobs`,
    { folder_path: folderPath }
  );
  return data;
}

export async function listSamples(params: SampleQuery, signal?: AbortSignal): Promise<SampleListResponse> {
  const { datasetId, search, fileType, fileStatus, tag, split, reviewStatus, annotationProgress, page, pageSize, sortBy, sortOrder } = params;
  const { data } = await client.get<SampleListResponse>(`/datasets/${datasetId}/samples`, {
    signal,
    params: {
      search: search || undefined,
      file_type: fileType || undefined,
      file_status: fileStatus || undefined,
      tag: tag || undefined,
      split: split || undefined,
      review_status: reviewStatus || undefined,
      annotation_progress: annotationProgress || undefined,
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_order: sortOrder
    }
  });
  return data;
}

export async function getSampleNavigation(
  params: Omit<SampleQuery, "fileType" | "page" | "pageSize"> & {
    sampleId?: number | null;
    queueScope?: AnnotationQueueScope;
  }
): Promise<SampleNavigationResponse> {
  const { datasetId, sampleId, search, fileStatus, tag, split, reviewStatus, annotationProgress, queueScope, sortBy, sortOrder } = params;
  const { data } = await client.get<SampleNavigationResponse>(`/datasets/${datasetId}/samples/navigation`, {
    params: {
      sample_id: sampleId || undefined,
      search: search || undefined,
      file_status: fileStatus || undefined,
      tag: tag || undefined,
      split: split || undefined,
      review_status: reviewStatus || undefined,
      annotation_progress: annotationProgress || undefined,
      queue_scope: queueScope || undefined,
      sort_by: sortBy,
      sort_order: sortOrder
    }
  });
  return data;
}

export async function getSample(sampleId: number): Promise<Sample> {
  const { data } = await client.get<Sample>(`/samples/${sampleId}`);
  return data;
}

export async function listSampleAnnotations(sampleId: number): Promise<AnnotationObject[]> {
  const { data } = await client.get<Omit<AnnotationObject, "client_id">[]>(`/samples/${sampleId}/annotations`);
  return data.map((item) => ({ ...item, client_id: `server-${item.id}` }));
}

export async function replaceSampleAnnotations(
  sampleId: number,
  payload: AnnotationReplaceRequest
): Promise<AnnotationObject[]> {
  const { data } = await client.put<Omit<AnnotationObject, "client_id">[]>(
    `/samples/${sampleId}/annotations`,
    payload
  );
  return data.map((item) => ({ ...item, client_id: `server-${item.id}` }));
}

export async function syncAnnotationClassesToSampleTags(sampleId: number): Promise<AnnotationTagSyncResult> {
  const { data } = await client.post<AnnotationTagSyncResult>(`/samples/${sampleId}/annotations/sync-sample-tags`);
  return data;
}

export async function updateSample(sampleId: number, payload: SampleUpdate): Promise<Sample> {
  const { data } = await client.patch<Sample>(`/samples/${sampleId}`, payload);
  return data;
}

export async function deleteSample(sampleId: number): Promise<SampleDeleteResult> {
  const { data } = await client.delete<SampleDeleteResult>(`/samples/${sampleId}`);
  return data;
}

export async function repairSample(sampleId: number, filePath: string): Promise<Sample> {
  const { data } = await client.patch<Sample>(`/samples/${sampleId}/repair`, {
    file_path: filePath
  });
  return data;
}

export async function batchUpdateSamples(
  datasetId: number,
  payload: BatchSampleUpdate
): Promise<BatchSampleUpdateResult> {
  const { data } = await client.patch<BatchSampleUpdateResult>(`/datasets/${datasetId}/samples/batch`, payload);
  return data;
}

export async function applySplitPlan(datasetId: number, payload: SplitPlanRequest): Promise<SplitPlanResult> {
  const { data } = await client.post<SplitPlanResult>(`/datasets/${datasetId}/split-plan`, payload);
  return data;
}

export async function deleteSamples(datasetId: number, sampleIds: number[]): Promise<SampleDeleteResult> {
  const { data } = await client.post<SampleDeleteResult>(`/datasets/${datasetId}/samples/delete`, {
    sample_ids: sampleIds
  });
  return data;
}

export async function repairMissingSamples(
  datasetId: number,
  payload: MissingSampleRepairRequest
): Promise<MissingSampleRepairResult> {
  const { data } = await client.post<MissingSampleRepairResult>(`/datasets/${datasetId}/repair-missing`, payload);
  return data;
}

export async function getSamplePreview(sampleId: number): Promise<SamplePreview> {
  const { data } = await client.get<SamplePreview>(`/samples/${sampleId}/preview`);
  return data;
}

export async function getDatasetStats(datasetId: number, signal?: AbortSignal): Promise<DatasetStats> {
  const { data } = await client.get<DatasetStats>(`/stats/datasets/${datasetId}`, { signal });
  return data;
}

export function getSampleFileUrl(sampleId: number): string {
  return `${API_BASE_URL}/samples/${sampleId}/file`;
}

export function getManifestUrl(datasetId: number, params?: Omit<SampleQuery, "datasetId" | "page" | "pageSize">): string {
  const searchParams = new URLSearchParams();
  if (params?.search) {
    searchParams.set("search", params.search);
  }
  if (params?.fileType) {
    searchParams.set("file_type", params.fileType);
  }
  if (params?.fileStatus) {
    searchParams.set("file_status", params.fileStatus);
  }
  if (params?.tag) {
    searchParams.set("tag", params.tag);
  }
  if (params?.split) {
    searchParams.set("split", params.split);
  }
  if (params?.reviewStatus) {
    searchParams.set("review_status", params.reviewStatus);
  }
  if (params?.sortBy) {
    searchParams.set("sort_by", params.sortBy);
  }
  if (params?.sortOrder) {
    searchParams.set("sort_order", params.sortOrder);
  }
  const query = searchParams.toString();
  return `${API_BASE_URL}/datasets/${datasetId}/export-manifest${query ? `?${query}` : ""}`;
}

export function getExportTemplateUrl(datasetId: number, format: string): string {
  const searchParams = new URLSearchParams({ format });
  return `${API_BASE_URL}/datasets/${datasetId}/export-template?${searchParams.toString()}`;
}

export async function getExportTemplate(datasetId: number, format: string): Promise<ExportTemplateResponse> {
  const { data } = await client.get<ExportTemplateResponse>(`/datasets/${datasetId}/export-template`, {
    params: { format }
  });
  return data;
}

export async function precheckAnnotationExport(
  datasetId: number,
  payload: AnnotationExportPrecheckRequest
): Promise<AnnotationExportPrecheckResponse> {
  const { data } = await client.post<AnnotationExportPrecheckResponse>(
    `/datasets/${datasetId}/annotation-export-precheck`,
    payload
  );
  return data;
}

export async function createAnnotationExportJob(
  datasetId: number,
  payload: AnnotationExportJobCreateRequest
): Promise<AnnotationExportJobCreateResponse> {
  const { data } = await client.post<AnnotationExportJobCreateResponse>(
    `/datasets/${datasetId}/annotation-export-jobs`,
    payload
  );
  return data;
}

export async function downloadJobArtifact(jobId: number): Promise<AnnotationExportDownload> {
  const response = await client.get<Blob>(`/jobs/${jobId}/artifact`, {
    responseType: "blob"
  });
  const disposition = String(response.headers["content-disposition"] ?? "");
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: response.data,
    filename: filenameMatch?.[1] ?? `job-${jobId}-artifact`
  };
}

export async function downloadAnnotationExport(
  datasetId: number,
  format: AnnotationExportFormat,
  query: AnnotationExportSampleQuery,
  includeEmpty: boolean
): Promise<AnnotationExportDownload> {
  const params = new URLSearchParams({
    format,
    include_empty: String(includeEmpty),
    sort_by: query.sort_by ?? "relative_path",
    sort_order: query.sort_order ?? "asc"
  });
  if (query.search) params.set("search", query.search);
  if (query.file_type) params.set("file_type", query.file_type);
  if (query.file_status) params.set("file_status", query.file_status);
  if (query.tag) params.set("tag", query.tag);
  if (query.split) params.set("split", query.split);
  if (query.review_status) params.set("review_status", query.review_status);
  query.sample_ids?.forEach((sampleId) => params.append("sample_ids", String(sampleId)));

  const response = await client.get<Blob>(
    `/datasets/${datasetId}/annotation-export?${params.toString()}`,
    { responseType: "blob" }
  );
  const disposition = String(response.headers["content-disposition"] ?? "");
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: response.data,
    filename: filenameMatch?.[1] ?? `dataset-${datasetId}-${format}`
  };
}
