import axios from "axios";
import {
  AlertTriangle,
  ArrowLeft,
  Bookmark,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  ClipboardCheck,
  Camera,
  Database,
  FileText,
  FolderInput,
  FolderOpen,
  HardDrive,
  Image as ImageIcon,
  ListChecks,
  Play,
  RefreshCw,
  Settings,
  ShieldCheck,
  Square,
  Tags,
  Video
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  applySplitPlan,
  batchUpdateSamples,
  createScanJob,
  createThumbnailMaintenanceJob,
  createThumbnailJob,
  deleteDataset,
  deleteSample,
  deleteSamples,
  getDuplicateReport,
  getDataset,
  getDatasetQualityReport,
  getDatasetStats,
  getExportTemplate,
  getManifestUrl,
  getJob,
  getSample,
  getTrainingReadiness,
  listTags,
  listJobs,
  listSamples,
  scanDataset,
  repairMissingSamples,
  repairSample,
  recordTrainingExport,
  updateDataset,
  updateSample
} from "../api/client";
import AnnotationExportModal from "../components/AnnotationExportModal";
import BatchActionBar from "../components/BatchActionBar";
import DatasetActionMenu from "../components/DatasetActionMenu";
import DirectoryExportModal from "../components/DirectoryExportModal";
import TriageDirectoryMappingModal from "../components/TriageDirectoryMappingModal";
import DatasetIssueModal from "../components/DatasetIssueModal";
import DatasetQualityModal from "../components/DatasetQualityModal";
import DatasetSettingsModal from "../components/DatasetSettingsModal";
import DatasetSavedViewModal from "../components/DatasetSavedViewModal";
import DatasetSnapshotModal from "../components/DatasetSnapshotModal";
import ExportPreviewModal, { type ExportPreview } from "../components/ExportPreviewModal";
import MetadataImportModal from "../components/MetadataImportModal";
import LabelmeImportModal from "../components/LabelmeImportModal";
import MissingRepairModal from "../components/MissingRepairModal";
import SampleDetailPanel from "../components/SampleDetailPanel";
import SampleGrid from "../components/SampleGrid";
import ScanModal from "../components/ScanModal";
import SearchFilterBar from "../components/SearchFilterBar";
import SplitPlanModal from "../components/SplitPlanModal";
import StatCard from "../components/StatCard";
import TagManagerModal from "../components/TagManagerModal";
import TagStatsModal from "../components/TagStatsModal";
import TrainingReadinessModal from "../components/TrainingReadinessModal";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type {
  AnnotationProgress,
  Dataset,
  DatasetQualityReport,
  DatasetStats,
  DuplicateReport,
  MissingSampleRepairResult,
  QualityIssue,
  Sample,
  SampleQuery,
  ScanResult,
  SplitPlanRequest,
  SplitPlanResult,
  Tag,
  TrainingReadinessConfigInput,
  TrainingReadinessReport,
  ReviewStatus
} from "../types/dataset";
import type { AnnotationExportFormat } from "../types/annotationExport";
import type { Job } from "../types/job";
import type {
  DatasetSavedView,
  DatasetSavedViewQuery,
  DatasetSavedViewSortField
} from "../types/datasetSavedView";
import { buildDefaultPendingQueue, buildReviewQueue, readAnnotationQueue } from "../utils/annotationQueue";
import {
  invalidateDatasetDetailCache,
  readDatasetDetailCache,
  writeDatasetDetailCache
} from "../utils/datasetDetailCache";
import { reviewStatusCopy, uiCopy } from "../utils/uiCopy";

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

const SAVED_VIEW_SORT_FIELDS = new Set<DatasetSavedViewSortField>([
  "created_at",
  "updated_at",
  "filename",
  "relative_path",
  "file_size",
  "extension",
  "file_type",
  "file_status",
  "split",
  "review_status",
  "annotation_progress"
]);

function savedViewSortField(value: string): DatasetSavedViewSortField {
  return SAVED_VIEW_SORT_FIELDS.has(value as DatasetSavedViewSortField)
    ? value as DatasetSavedViewSortField
    : "created_at";
}

function savedViewReviewStatus(value: string): ReviewStatus | undefined {
  return value === "not_reviewed" || value === "in_review" || value === "approved" || value === "rejected"
    ? value
    : undefined;
}

function savedViewAnnotationProgress(value: string): AnnotationProgress | undefined {
  return value === "not_started" || value === "in_progress" || value === "completed_empty" || value === "completed_with_objects"
    ? value
    : undefined;
}

function scanResultFromJob(job: Job): ScanResult | null {
  const result = job.result;
  if (!result) {
    return null;
  }
  const numericFields: Array<keyof ScanResult> = [
    "dataset_id",
    "scanned",
    "imported",
    "updated",
    "unchanged",
    "missing",
    "skipped_existing",
    "skipped_unsupported",
    "hashed",
    "hash_skipped_unchanged",
    "batches_committed",
    "error_count"
  ];
  if (
    numericFields.some((field) => typeof result[field] !== "number")
    || !Array.isArray(result.errors)
    || result.errors.some((error) => typeof error !== "string")
  ) {
    return null;
  }
  return result as unknown as ScanResult;
}

function downloadTextFile(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value: unknown): string {
  const text = Array.isArray(value) || (value && typeof value === "object") ? JSON.stringify(value) : String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.split('"').join('""')}"` : text;
}

function exportTemplateToCsv(payload: Record<string, unknown>): string {
  const columns = Array.isArray(payload.columns) ? payload.columns.map(String) : [];
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  const lines = [columns.map(csvCell).join(",")];
  for (const row of rows) {
    if (row && typeof row === "object") {
      const record = row as Record<string, unknown>;
      lines.push(columns.map((column) => csvCell(record[column])).join(","));
    }
  }
  return `${lines.join("\n")}\n`;
}

export default function DatasetDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const datasetId = Number(params.datasetId);
  const [pageSearchParams, setPageSearchParams] = useSearchParams();
  const [initialCache] = useState(() => readDatasetDetailCache(datasetId));
  const [dataset, setDataset] = useState<Dataset | null>(initialCache?.dataset ?? null);
  const [stats, setStats] = useState<DatasetStats | null>(initialCache?.stats ?? null);
  const [samples, setSamples] = useState<Sample[]>(initialCache?.samples ?? []);
  const [thumbnailPrefetchSampleIds, setThumbnailPrefetchSampleIds] = useState<number[]>([]);
  const [sampleTotal, setSampleTotal] = useState(initialCache?.sampleTotal ?? 0);
  const [duplicateReport, setDuplicateReport] = useState<DuplicateReport | null>(initialCache?.duplicateReport ?? null);
  const [qualityReport, setQualityReport] = useState<DatasetQualityReport | null>(null);
  const [availableTags, setAvailableTags] = useState<Tag[]>(initialCache?.availableTags ?? []);
  const [selected, setSelected] = useState<Sample | null>(null);
  const [selectedSampleIds, setSelectedSampleIds] = useState<Set<number>>(new Set());
  const [lastScanResult, setLastScanResult] = useState<ScanResult | null>(null);
  const [search, setSearch] = useState(initialCache?.filters.search ?? "");
  const [fileType, setFileType] = useState(initialCache?.filters.fileType ?? "");
  const [fileStatus, setFileStatus] = useState(initialCache?.filters.fileStatus ?? "");
  const [tag, setTag] = useState(initialCache?.filters.tag ?? "");
  const [split, setSplit] = useState(initialCache?.filters.split ?? "");
  const [reviewStatus, setReviewStatus] = useState(initialCache?.filters.reviewStatus ?? "");
  const [annotationProgress, setAnnotationProgress] = useState(initialCache?.filters.annotationProgress ?? "");
  const [page, setPage] = useState(initialCache?.filters.page ?? 1);
  const [pageSize, setPageSize] = useState(initialCache?.filters.pageSize ?? 60);
  const [sortBy, setSortBy] = useState(initialCache?.filters.sortBy ?? "created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(initialCache?.filters.sortOrder ?? "desc");
  const [exportFormat, setExportFormat] = useState("manifest");
  const [scanOpen, setScanOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [tagStatsOpen, setTagStatsOpen] = useState(false);
  const [metadataImportOpen, setMetadataImportOpen] = useState(false);
  const [labelmeImportOpen, setLabelmeImportOpen] = useState(false);
  const [missingRepairOpen, setMissingRepairOpen] = useState(false);
  const [splitPlanOpen, setSplitPlanOpen] = useState(false);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [trainingReadinessOpen, setTrainingReadinessOpen] = useState(false);
  const [issueModal, setIssueModal] = useState<"missing" | "duplicate" | null>(null);
  const [exportPreview, setExportPreview] = useState<ExportPreview | null>(null);
  const [annotationExportOpen, setAnnotationExportOpen] = useState(false);
  const [directoryExportOpen, setDirectoryExportOpen] = useState(false);
  const [directoryMappingOpen, setDirectoryMappingOpen] = useState(false);
  const [snapshotOpen, setSnapshotOpen] = useState(false);
  const [savedViewOpen, setSavedViewOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanJobId, setScanJobId] = useState<number | null>(null);
  const [scanNotice, setScanNotice] = useState<string | null>(null);
  const [thumbnailJobId, setThumbnailJobId] = useState<number | null>(null);
  const [thumbnailJobsAvailable, setThumbnailJobsAvailable] = useState(true);
  const [thumbnailRevision, setThumbnailRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [deletingDataset, setDeletingDataset] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [deletingSamples, setDeletingSamples] = useState(false);
  const [repairingSample, setRepairingSample] = useState(false);
  const [repairingMissing, setRepairingMissing] = useState(false);
  const [applyingSplitPlan, setApplyingSplitPlan] = useState(false);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [trainingReadinessLoading, setTrainingReadinessLoading] = useState(false);
  const [missingRepairResult, setMissingRepairResult] = useState<MissingSampleRepairResult | null>(null);
  const [splitPlanResult, setSplitPlanResult] = useState<SplitPlanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qualityError, setQualityError] = useState<string | null>(null);
  const [trainingReadiness, setTrainingReadiness] = useState<TrainingReadinessReport | null>(null);
  const [trainingReadinessError, setTrainingReadinessError] = useState<string | null>(null);

  useEffect(() => {
    const openDirectoryExport = pageSearchParams.get("directoryExport") === "1";
    const openDirectoryMapping = pageSearchParams.get("directoryMapping") === "1";
    if (!openDirectoryExport && !openDirectoryMapping) return;
    if (openDirectoryExport) setDirectoryExportOpen(true);
    if (openDirectoryMapping) setDirectoryMappingOpen(true);
    setPageSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("directoryExport");
      next.delete("directoryMapping");
      return next;
    }, { replace: true });
  }, [pageSearchParams, setPageSearchParams]);
  const autoScannedDatasetIds = useRef<Set<number>>(new Set());
  const samplesSectionRef = useRef<HTMLElement | null>(null);
  const overviewRequestIdRef = useRef(0);
  const samplesRequestIdRef = useRef(0);
  const thumbnailRequestKeyRef = useRef("");
  const thumbnailMaintenanceRequestedRef = useRef(false);
  const detailCacheStateRef = useRef<Parameters<typeof writeDatasetDetailCache>[0] | null>(null);
  const debouncedSearch = useDebouncedValue(search);
  const debouncedTag = useDebouncedValue(tag);

  const loadOverview = useCallback(async (signal?: AbortSignal) => {
    const requestId = ++overviewRequestIdRef.current;
    const [nextDataset, nextStats, nextDuplicateReport, nextTags] = await Promise.all([
      getDataset(datasetId, signal),
      getDatasetStats(datasetId, signal),
      getDuplicateReport(datasetId, { signal }),
      listTags(datasetId, signal)
    ]);
    if (signal?.aborted || requestId !== overviewRequestIdRef.current) {
      return;
    }
    setDataset(nextDataset);
    setStats(nextStats);
    setDuplicateReport(nextDuplicateReport);
    setAvailableTags(nextTags);
  }, [datasetId]);

  const loadSamples = useCallback(async (signal?: AbortSignal) => {
    const requestId = ++samplesRequestIdRef.current;
    const nextSamples = await listSamples({
      datasetId,
      search: debouncedSearch,
      fileType,
      fileStatus,
      tag: debouncedTag,
      split,
      reviewStatus,
      annotationProgress: annotationProgress as SampleQuery["annotationProgress"],
      page,
      pageSize,
      sortBy,
      sortOrder,
      thumbnailPrefetch: 12
    }, signal);
    if (signal?.aborted || requestId !== samplesRequestIdRef.current) {
      return;
    }
    setSamples(nextSamples.items);
    setThumbnailPrefetchSampleIds(nextSamples.thumbnail_prefetch_sample_ids);
    setSampleTotal(nextSamples.total);
    if (nextSamples.page !== page) {
      setPage(nextSamples.page);
    }
  }, [datasetId, debouncedSearch, debouncedTag, fileType, fileStatus, split, reviewStatus, annotationProgress, page, pageSize, sortBy, sortOrder]);

  const loadQualityReport = useCallback(async () => {
    setQualityLoading(true);
    setQualityError(null);
    try {
      setQualityReport(await getDatasetQualityReport(datasetId));
    } catch {
      setQualityError("质量检查失败，请确认后端服务可用后重试");
    } finally {
      setQualityLoading(false);
    }
  }, [datasetId]);

  const loadTrainingReadiness = useCallback(async () => {
    setTrainingReadinessLoading(true);
    setTrainingReadinessError(null);
    try {
      setTrainingReadiness(await getTrainingReadiness(datasetId));
    } catch {
      setTrainingReadinessError("训练准备状态加载失败，请确认后端服务可用后重试");
    } finally {
      setTrainingReadinessLoading(false);
    }
  }, [datasetId]);

  useEffect(() => {
    if (!Number.isFinite(datasetId)) {
      return;
    }
    const controller = new AbortController();
    setError(null);
    void loadOverview(controller.signal).catch(() => {
      if (!controller.signal.aborted) {
        setError("数据集加载失败");
      }
    });
    return () => controller.abort();
  }, [datasetId, loadOverview]);

  useEffect(() => {
    if (!Number.isFinite(datasetId)) {
      return;
    }
    const controller = new AbortController();
    void loadSamples(controller.signal).catch(() => {
      if (!controller.signal.aborted) {
        setError("样本加载失败");
      }
    });
    return () => controller.abort();
  }, [datasetId, loadSamples]);

  useEffect(() => {
    thumbnailRequestKeyRef.current = "";
    setThumbnailJobId(null);
    setThumbnailJobsAvailable(true);
    setThumbnailRevision(0);
    setThumbnailPrefetchSampleIds([]);
  }, [datasetId]);

  useEffect(() => {
    if (!Number.isFinite(datasetId) || !thumbnailJobsAvailable) return;
    const imageSamples = samples.filter(
      (sample) => sample.file_type === "image" && sample.file_status === "normal"
    );
    if (imageSamples.length === 0) return;
    const requestKey = `${datasetId}:${imageSamples
      .map((sample) => `${sample.id}:${sample.file_hash}`)
      .join(",")}:prefetch:${thumbnailPrefetchSampleIds.join(",")}`;
    if (thumbnailRequestKeyRef.current === requestKey) return;
    thumbnailRequestKeyRef.current = requestKey;

    void createThumbnailJob(
      datasetId,
      imageSamples.map((sample) => sample.id),
      thumbnailPrefetchSampleIds
    )
      .then((response) => {
        if (thumbnailRequestKeyRef.current !== requestKey) return;
        if (response.job) {
          setThumbnailJobId(response.job.id);
          window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
        } else {
          setThumbnailRevision((current) => current + 1);
        }
        if (!thumbnailMaintenanceRequestedRef.current) {
          thumbnailMaintenanceRequestedRef.current = true;
          void createThumbnailMaintenanceJob()
            .then((maintenance) => {
              if (maintenance.job) {
                window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
              }
            })
            .catch(() => {
              // Thumbnail previews stay usable if optional maintenance is unavailable.
            });
        }
      })
      .catch((caught) => {
        if (thumbnailRequestKeyRef.current !== requestKey) return;
        if (axios.isAxiosError(caught) && caught.response?.status === 409) {
          setThumbnailJobsAvailable(false);
          return;
        }
        thumbnailRequestKeyRef.current = "";
      });
  }, [datasetId, samples, thumbnailJobsAvailable, thumbnailPrefetchSampleIds]);

  useEffect(() => {
    if (thumbnailJobId === null) return;
    let disposed = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const job = await getJob(thumbnailJobId);
        if (disposed) return;
        if (job.status === "queued" || job.status === "running") {
          timer = window.setTimeout(() => void poll(), 750);
          return;
        }
        setThumbnailJobId(null);
        if (job.status === "succeeded") {
          setThumbnailRevision((current) => current + 1);
        }
        window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
      } catch {
        if (!disposed) setThumbnailJobId(null);
      }
    };

    void poll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [thumbnailJobId]);

  useEffect(() => {
    const handleJobAction = (event: Event) => {
      const job = (event as CustomEvent<{ job?: Job }>).detail?.job;
      if (
        job?.job_type === "thumbnail.generate"
        && job.dataset_id === datasetId
        && (job.status === "queued" || job.status === "running")
      ) {
        setThumbnailJobsAvailable(true);
        setThumbnailJobId(job.id);
      }
    };
    window.addEventListener("dataset-manager:job-action", handleJobAction);
    return () => window.removeEventListener("dataset-manager:job-action", handleJobAction);
  }, [datasetId]);

  detailCacheStateRef.current = {
    datasetId,
    dataset,
    stats,
    samples,
    sampleTotal,
    duplicateReport,
    availableTags,
    filters: {
      search,
      fileType,
      fileStatus,
      tag,
      split,
      reviewStatus,
      annotationProgress,
      page,
      pageSize,
      sortBy,
      sortOrder
    },
    savedAt: Date.now()
  };

  useEffect(() => () => {
    if (detailCacheStateRef.current?.datasetId === datasetId) {
      writeDatasetDetailCache(detailCacheStateRef.current);
    }
  }, [datasetId]);

  const imageCount = stats?.by_file_type.image ?? 0;
  const videoCount = stats?.by_file_type.video ?? 0;
  const missingCount = stats?.by_status.missing ?? 0;
  const permissionDeniedCount = stats?.by_status.permission_denied ?? 0;
  const unavailableCount = missingCount + permissionDeniedCount;
  const duplicateSampleCount = stats?.duplicate_samples ?? 0;
  const duplicateGroupCount = stats?.duplicate_groups ?? 0;
  const completedGeometrySamples =
    (stats?.by_annotation_progress.completed_empty ?? 0)
    + (stats?.by_annotation_progress.completed_with_objects ?? 0);
  const annotationCount = stats?.annotation_count ?? 0;
  const tagCount = useMemo(() => Object.keys(stats?.tag_counts ?? {}).length, [stats]);
  const geometryTask = dataset?.task_capabilities.supported === true && dataset.task_capabilities.annotation_mode === "geometry";
  const classificationTask = dataset?.task_type === "classification";
  const storedAnnotationQueue = useMemo(
    () => geometryTask ? readAnnotationQueue(datasetId) : null,
    [datasetId, geometryTask]
  );
  const taskCompletedSamples = classificationTask
    ? Math.max((stats?.sample_count ?? 0) - (stats?.untagged_samples ?? 0), 0)
    : completedGeometrySamples;
  const workflowTotal = classificationTask ? stats?.sample_count ?? 0 : imageCount;
  const workflowPending = Math.max(workflowTotal - taskCompletedSamples, 0);
  const rejectedCount = stats?.by_review_status.rejected ?? 0;
  const keyBlockers = useMemo(() => {
    const blockers: Array<{ title: string; detail: string; tone: "danger" | "warning" }> = [];
    if (dataset && !dataset.task_capabilities.supported) {
      blockers.push({
        title: "任务类型需要迁移",
        detail: dataset.task_capabilities.unsupported_reason ?? "请先选择受支持的任务类型。",
        tone: "danger"
      });
    }
    if (dataset && !dataset.root_path) {
      blockers.push({
        title: "尚未设置扫描目录",
        detail: "设置本地目录后才能扫描和更新样本。",
        tone: "warning"
      });
    }
    if (geometryTask && (stats?.sample_count ?? 0) > 0 && imageCount === 0) {
      blockers.push({
        title: "没有可用于几何标注的图片",
        detail: "当前任务需要正常图片样本，请检查扫描目录或文件类型。",
        tone: "warning"
      });
    }
    if (unavailableCount > 0) {
      blockers.push({
        title: `${unavailableCount} 个文件不可用`,
        detail: "缺失或无权限文件会阻断预览和训练导出。",
        tone: "danger"
      });
    }
    if (rejectedCount > 0) {
      blockers.push({
        title: `${rejectedCount} 个样本审核未通过`,
        detail: "已拒绝样本不应直接进入训练导出。",
        tone: "warning"
      });
    }
    return blockers;
  }, [dataset, geometryTask, imageCount, rejectedCount, stats?.sample_count, unavailableCount]);
  const defaultAnnotationExportFormat = useMemo<AnnotationExportFormat>(() => {
    const value = dataset?.task_capabilities.default_export_format;
    return value === "coco_detection" || value === "coco_segmentation" ? value : "labelme";
  }, [dataset?.task_capabilities.default_export_format]);
  const annotationLabelRows = useMemo(
    () => Object.entries(stats?.by_annotation_label ?? {}).sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0])).slice(0, 5),
    [stats]
  );
  const visibleSampleIds = useMemo(() => samples.map((sample) => sample.id), [samples]);
  const annotationExportQuery = useMemo(
    () => ({
      search: debouncedSearch || undefined,
      file_type: fileType || undefined,
      file_status: fileStatus || undefined,
      tag: debouncedTag || undefined,
      split: split || undefined,
      review_status: reviewStatus || undefined,
      annotation_progress: annotationProgress || undefined,
      sort_by: sortBy,
      sort_order: sortOrder
    }),
    [annotationProgress, debouncedSearch, debouncedTag, fileStatus, fileType, reviewStatus, sortBy, sortOrder, split]
  );
  const savedViewQuery = useMemo<DatasetSavedViewQuery>(
    () => ({
      search: debouncedSearch || undefined,
      file_type: fileType || undefined,
      file_status: fileStatus || undefined,
      tag: debouncedTag || undefined,
      split: split || undefined,
      review_status: savedViewReviewStatus(reviewStatus),
      annotation_progress: savedViewAnnotationProgress(annotationProgress),
      sort_by: savedViewSortField(sortBy),
      sort_order: sortOrder
    }),
    [annotationProgress, debouncedSearch, debouncedTag, fileStatus, fileType, reviewStatus, sortBy, sortOrder, split]
  );
  const annotationExportSelectedSampleIds = useMemo(
    () => Array.from(selectedSampleIds),
    [selectedSampleIds]
  );
  const selectedVisibleCount = useMemo(
    () => visibleSampleIds.filter((sampleId) => selectedSampleIds.has(sampleId)).length,
    [selectedSampleIds, visibleSampleIds]
  );
  const allVisibleSelected = visibleSampleIds.length > 0 && selectedVisibleCount === visibleSampleIds.length;
  const pageCount = Math.max(Math.ceil(sampleTotal / pageSize), 1);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, debouncedTag, fileType, fileStatus, split, reviewStatus, annotationProgress, sortBy, sortOrder]);

  useEffect(() => {
    setExportFormat(dataset?.task_capabilities.default_export_format === "csv" ? "csv" : "manifest");
    if (dataset?.task_type === "classification") {
      setAnnotationProgress("");
    }
  }, [dataset?.id, dataset?.task_capabilities.default_export_format, dataset?.task_type]);

  useEffect(() => {
    if (qualityOpen && Number.isFinite(datasetId)) {
      void loadQualityReport();
    }
  }, [datasetId, loadQualityReport, qualityOpen]);

  useEffect(() => {
    if (trainingReadinessOpen && Number.isFinite(datasetId)) {
      void loadTrainingReadiness();
    }
  }, [datasetId, loadTrainingReadiness, trainingReadinessOpen]);

  const startScan = useCallback(async (
    targetDatasetId: number,
    path: string,
    closeModal: boolean
  ) => {
    setScanning(true);
    setError(null);
    setScanNotice(null);
    try {
      const response = await createScanJob(targetDatasetId, path);
      setScanJobId(response.job.id);
      setScanNotice(response.created ? "扫描任务已提交，可继续浏览当前数据" : "已有扫描任务正在运行，已恢复状态跟踪");
      if (closeModal) setScanOpen(false);
      window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
      return;
    } catch (caught) {
      if (!axios.isAxiosError(caught) || caught.response?.status !== 409) {
        setError("扫描任务提交失败，请检查目录和后端服务");
        setScanning(false);
        return;
      }
    }

    setScanNotice("任务中心尚未启用，本次使用兼容扫描；完成前请保持页面打开");
    try {
      const result = await scanDataset(targetDatasetId, path);
      setLastScanResult(result);
      await Promise.all([loadOverview(), loadSamples()]);
      setScanNotice(`兼容扫描完成：新增 ${result.imported}，变更 ${result.updated}，未变 ${result.unchanged}`);
      if (closeModal) setScanOpen(false);
    } catch {
      setScanNotice(null);
      setError("兼容扫描失败，请检查目录是否存在且可读取");
    } finally {
      setScanning(false);
    }
  }, [loadOverview, loadSamples]);

  useEffect(() => {
    if (!Number.isFinite(datasetId)) return;
    let disposed = false;
    setScanJobId(null);
    setScanning(false);
    setScanNotice(null);
    setLastScanResult(null);
    void listJobs(20, { datasetId, jobType: "dataset.scan" })
      .then((response) => {
        if (disposed) return;
        const active = response.items.find((job) => job.status === "queued" || job.status === "running");
        if (active) {
          setScanJobId(active.id);
          setScanning(true);
          setScanNotice("已恢复正在运行的扫描任务");
        }
      })
      .catch(() => {
        // A 409 means the old database will use the synchronous compatibility path.
      });
    return () => {
      disposed = true;
    };
  }, [datasetId]);

  useEffect(() => {
    if (scanJobId === null) return;
    let disposed = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const job = await getJob(scanJobId);
        if (disposed) return;
        if (job.status === "queued" || job.status === "running") {
          timer = window.setTimeout(() => void poll(), 750);
          return;
        }

        const result = scanResultFromJob(job);
        if (result) setLastScanResult(result);
        setScanJobId(null);
        setScanning(false);
        if (job.status === "succeeded") {
          setScanNotice(result
            ? `扫描完成：新增 ${result.imported}，变更 ${result.updated}，未变 ${result.unchanged}`
            : "扫描任务已完成");
        } else if (job.status === "cancelled" || job.status === "interrupted") {
          setScanNotice(result
            ? `扫描${job.status === "cancelled" ? "已取消" : "已中断"}，已安全提交 ${result.imported + result.updated + result.unchanged} 条`
            : `扫描${job.status === "cancelled" ? "已取消" : "已中断"}`);
        } else {
          const message = typeof job.error?.message === "string" ? job.error.message : "请在任务抽屉查看错误";
          setScanNotice(null);
          setError(`扫描任务失败：${message}`);
        }
        window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
        try {
          await Promise.all([loadOverview(), loadSamples()]);
        } catch {
          setError("扫描任务已结束，但数据刷新失败，请手动刷新页面");
        }
      } catch {
        if (!disposed) {
          setScanNotice(null);
          setError("扫描任务状态读取失败，请在任务抽屉中查看");
          setScanning(false);
          setScanJobId(null);
        }
      }
    };

    void poll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [loadOverview, loadSamples, scanJobId]);

  useEffect(() => {
    if (!dataset?.auto_scan_on_open || !dataset.root_path || autoScannedDatasetIds.current.has(dataset.id)) {
      return;
    }
    autoScannedDatasetIds.current.add(dataset.id);
    void startScan(dataset.id, dataset.root_path, false);
  }, [dataset, startScan]);

  async function handleScan(path: string) {
    await startScan(datasetId, path, true);
  }

  async function handleSelect(sample: Sample) {
    setSelected(await getSample(sample.id));
  }

  function handleAnnotate(sample: Sample) {
    if (!geometryTask) {
      if (classificationTask) {
        setSelected(sample);
      } else {
        setSettingsOpen(true);
      }
      return;
    }
    const params = new URLSearchParams({
      sample: String(sample.id),
      queue: "current_filter",
      resume: "1",
      sortBy,
      sortOrder
    });
    if (debouncedSearch) {
      params.set("search", debouncedSearch);
    }
    if (fileStatus) {
      params.set("fileStatus", fileStatus);
    }
    if (debouncedTag) {
      params.set("tag", debouncedTag);
    }
    if (split) {
      params.set("split", split);
    }
    if (reviewStatus) {
      params.set("reviewStatus", reviewStatus);
    }
    if (annotationProgress) {
      params.set("annotationProgress", annotationProgress);
    }
    navigate(`/datasets/${datasetId}/annotate?${params.toString()}`);
  }

  function focusSampleWorkspace(nextFilters: {
    fileType?: string;
    tag?: string;
    annotationProgress?: string;
  } = {}) {
    applyGlobalFilters(nextFilters);
    window.requestAnimationFrame(() => {
      samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function handlePrimaryAction() {
    if (!dataset) {
      return;
    }
    if (!dataset.task_capabilities.supported) {
      setSettingsOpen(true);
      return;
    }
    if (!dataset.root_path) {
      setScanOpen(true);
      return;
    }
    if ((stats?.sample_count ?? 0) === 0 || (geometryTask && imageCount === 0)) {
      void handleScan(dataset.root_path);
      return;
    }
    if (unavailableCount > 0) {
      setIssueModal("missing");
      return;
    }
    if (classificationTask) {
      focusSampleWorkspace({ tag: workflowPending > 0 ? "__untagged__" : undefined });
      return;
    }

    const query = workflowPending > 0
      ? storedAnnotationQueue?.query ?? buildDefaultPendingQueue()
      : buildReviewQueue(storedAnnotationQueue);
    navigate(`/datasets/${datasetId}/annotate?${query}`);
  }

  const primaryActionLabel = !dataset
    ? "加载中"
    : !dataset.task_capabilities.supported
      ? "修改任务类型"
      : !dataset.root_path
        ? "设置扫描目录"
        : (stats?.sample_count ?? 0) === 0 || (geometryTask && imageCount === 0)
          ? "扫描样本"
          : unavailableCount > 0
            ? "处理不可用文件"
            : classificationTask
              ? workflowPending > 0 ? "整理未分类样本" : "查看分类结果"
              : workflowPending > 0
                ? storedAnnotationQueue ? "继续标注" : "开始标注"
                : "复查标注结果";

  async function handleSave(payload: { split: string | null; notes: string | null; tags: string[] }) {
    if (!selected) {
      return;
    }
    setSaving(true);
    try {
      const updated = await updateSample(selected.id, payload);
      setSelected(updated);
      await Promise.all([loadOverview(), loadSamples()]);
    } finally {
      setSaving(false);
    }
  }

  async function handleDatasetSave(payload: Parameters<typeof updateDataset>[1]) {
    setSettingsSaving(true);
    try {
      const updated = await updateDataset(datasetId, payload);
      setDataset(updated);
      await loadOverview();
      setSettingsOpen(false);
    } finally {
      setSettingsSaving(false);
    }
  }

  async function handleDatasetDelete() {
    setDeletingDataset(true);
    try {
      await deleteDataset(datasetId);
      detailCacheStateRef.current = null;
      invalidateDatasetDetailCache(datasetId);
      navigate("/");
    } finally {
      setDeletingDataset(false);
    }
  }

  function handleToggleSelect(sampleId: number) {
    setSelectedSampleIds((current) => {
      const next = new Set(current);
      if (next.has(sampleId)) {
        next.delete(sampleId);
      } else {
        next.add(sampleId);
      }
      return next;
    });
  }

  async function handleBatchApply(payload: { split: string | null; addTags: string[] }) {
    const sampleIds = Array.from(selectedSampleIds);
    if (sampleIds.length === 0) {
      return;
    }
    setBatchBusy(true);
    try {
      await batchUpdateSamples(datasetId, {
        sample_ids: sampleIds,
        split: payload.split,
        add_tags: payload.addTags
      });
      setSelectedSampleIds(new Set());
      await Promise.all([loadOverview(), loadSamples()]);
    } finally {
      setBatchBusy(false);
    }
  }

  async function handleDeleteSelected() {
    const sampleIds = Array.from(selectedSampleIds);
    if (sampleIds.length === 0) {
      return;
    }
    const confirmed = window.confirm(`只删除 ${sampleIds.length} 个样本的数据库记录，不删除本地文件。确定继续？`);
    if (!confirmed) {
      return;
    }
    setDeletingSamples(true);
    try {
      await deleteSamples(datasetId, sampleIds);
      setSelectedSampleIds(new Set());
      if (selected && sampleIds.includes(selected.id)) {
        setSelected(null);
      }
      await Promise.all([loadOverview(), loadSamples()]);
    } finally {
      setDeletingSamples(false);
    }
  }

  async function handleDeleteCurrentSample() {
    if (!selected) {
      return;
    }
    const confirmed = window.confirm(`只删除样本记录“${selected.filename}”，不删除本地文件。确定继续？`);
    if (!confirmed) {
      return;
    }
    setDeletingSamples(true);
    try {
      await deleteSample(selected.id);
      setSelectedSampleIds((current) => {
        const next = new Set(current);
        next.delete(selected.id);
        return next;
      });
      setSelected(null);
      await Promise.all([loadOverview(), loadSamples()]);
    } finally {
      setDeletingSamples(false);
    }
  }

  async function handleRepairCurrentSample(filePath: string) {
    if (!selected) {
      return;
    }
    setRepairingSample(true);
    setError(null);
    try {
      const repaired = await repairSample(selected.id, filePath);
      setSelected(repaired);
      await Promise.all([loadOverview(), loadSamples()]);
    } catch {
      setError("样本修复失败，请确认文件路径存在且类型受支持");
    } finally {
      setRepairingSample(false);
    }
  }

  async function handleRepairMissing(rootPath: string, updateDatasetRoot: boolean) {
    setRepairingMissing(true);
    setError(null);
    try {
      const result = await repairMissingSamples(datasetId, {
        root_path: rootPath,
        update_dataset_root: updateDatasetRoot
      });
      setMissingRepairResult(result);
      await Promise.all([loadOverview(), loadSamples()]);
    } catch {
      setError("缺失文件修复失败，请确认目录存在且可读取");
    } finally {
      setRepairingMissing(false);
    }
  }

  async function handleApplySplitPlan(payload: SplitPlanRequest) {
    setApplyingSplitPlan(true);
    setError(null);
    try {
      const result = await applySplitPlan(datasetId, payload);
      setSplitPlanResult(result);
      await Promise.all([loadOverview(), loadSamples()]);
    } catch {
      setError("数据集划分失败，请检查比例设置和样本数量");
    } finally {
      setApplyingSplitPlan(false);
    }
  }

  async function handleExport(
    formatOverride?: string,
    trainingConfig?: TrainingReadinessConfigInput
  ) {
    setError(null);
    try {
      const targetFormat = formatOverride ?? exportFormat;
      if (targetFormat === "csv") {
        const template = await getExportTemplate(datasetId, targetFormat);
        const content = exportTemplateToCsv(template.payload);
        setExportPreview({
          title: "CSV 标签表",
          filename: `dataset-${datasetId}-labels.csv`,
          mimeType: "text/csv;charset=utf-8",
          content,
          summary: template.description,
          trainingConfig
        });
        return;
      }
      const response = await fetch(
        getManifestUrl(datasetId, {
          search: debouncedSearch,
          fileType,
          fileStatus,
          tag: debouncedTag,
          split,
          reviewStatus,
          sortBy,
          sortOrder
        })
      );
      if (!response.ok) {
        throw new Error("Manifest export failed.");
      }
      const manifest = await response.json();
      setExportPreview({
        title: "Manifest 审计清单",
        filename: `dataset-${datasetId}-manifest.json`,
        mimeType: "application/json;charset=utf-8",
        content: `${JSON.stringify(manifest, null, 2)}\n`,
        summary: `当前筛选条件下导出 ${manifest.exported_sample_count ?? 0} 个样本。`
      });
    } catch {
      setError("导出失败，请稍后重试");
    }
  }

  async function handleDownloadExport() {
    if (!exportPreview) {
      return;
    }
    const preview = exportPreview;
    downloadTextFile(preview.filename, preview.content, preview.mimeType);
    setExportPreview(null);
    if (preview.trainingConfig) {
      try {
        await recordTrainingExport(datasetId, preview.trainingConfig);
      } catch {
        setError("文件已经下载，但未能记录最近导出时间；下载内容不受影响");
      }
    }
  }

  function clearFilters() {
    setSearch("");
    setFileType("");
    setFileStatus("");
    setTag("");
    setSplit("");
    setReviewStatus("");
    setAnnotationProgress("");
    setPage(1);
  }

  function applyGlobalFilters(nextFilters: {
    fileType?: string;
    fileStatus?: string;
    tag?: string;
    split?: string;
    reviewStatus?: string;
    annotationProgress?: string;
  }) {
    setSearch("");
    setFileType(nextFilters.fileType ?? "");
    setFileStatus(nextFilters.fileStatus ?? "");
    setTag(nextFilters.tag ?? "");
    setSplit(nextFilters.split ?? "");
    setReviewStatus(nextFilters.reviewStatus ?? "");
    setAnnotationProgress(nextFilters.annotationProgress ?? "");
    setPage(1);
  }

  function applySavedView(savedView: DatasetSavedView) {
    const query = savedView.sample_query;
    setSearch(query.search ?? "");
    setFileType(query.file_type ?? "");
    setFileStatus(query.file_status ?? "");
    setTag(query.tag ?? "");
    setSplit(query.split ?? "");
    setReviewStatus(query.review_status ?? "");
    setAnnotationProgress(classificationTask ? "" : query.annotation_progress ?? "");
    setSortBy(query.sort_by);
    setSortOrder(query.sort_order);
    setSelectedSampleIds(new Set());
    setPage(1);
    setSavedViewOpen(false);
    window.requestAnimationFrame(() => {
      samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function startSavedViewQueue(savedView: DatasetSavedView) {
    const query = savedView.sample_query;
    const params = new URLSearchParams({
      queue: savedView.queue_scope,
      resume: "1",
      sortBy: query.sort_by,
      sortOrder: query.sort_order
    });
    if (savedView.queue_scope === "current_filter") {
      if (query.search) params.set("search", query.search);
      if (query.file_status) params.set("fileStatus", query.file_status);
      if (query.tag) params.set("tag", query.tag);
      if (query.split) params.set("split", query.split);
      if (query.review_status) params.set("reviewStatus", query.review_status);
      if (query.annotation_progress) params.set("annotationProgress", query.annotation_progress);
    } else if (savedView.queue_scope === "current_split" && query.split) {
      params.set("queueSplit", query.split);
    }
    navigate(`/datasets/${datasetId}/annotate?${params.toString()}`);
  }

  function filterFileType(nextFileType: string) {
    applyGlobalFilters({ fileType: nextFileType });
  }

  function toggleVisibleSamples() {
    setSelectedSampleIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected) {
        visibleSampleIds.forEach((sampleId) => next.delete(sampleId));
      } else {
        visibleSampleIds.forEach((sampleId) => next.add(sampleId));
      }
      return next;
    });
  }

  function filterMissing(status: "missing" | "permission_denied" = "missing") {
    applyGlobalFilters({ fileStatus: status });
    setIssueModal(null);
    setQualityOpen(false);
  }

  function filterDuplicates() {
    applyGlobalFilters({ fileStatus: "duplicate" });
    setIssueModal(null);
    window.requestAnimationFrame(() => {
      samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function filterDuplicateHash(fileHash: string) {
    applyGlobalFilters({ fileStatus: "duplicate" });
    setSearch(fileHash);
    setIssueModal(null);
    window.requestAnimationFrame(() => {
      samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function openMissingRepair() {
    setIssueModal(null);
    setQualityOpen(false);
    setMissingRepairResult(null);
    setMissingRepairOpen(true);
  }

  async function openQualityIssue(issue: QualityIssue) {
    setQualityOpen(false);
    if (!issue.sample_id) {
      return;
    }
    if (issue.code === "FILE_UNAVAILABLE" || issue.code === "SAMPLE_TAG_MISSING") {
      try {
        setSelected(await getSample(issue.sample_id));
      } catch {
        setError("问题样本加载失败");
      }
      return;
    }
    const params = new URLSearchParams({ sample: String(issue.sample_id), sortBy, sortOrder });
    if (issue.annotation_id) {
      params.set("annotation", String(issue.annotation_id));
    }
    navigate(`/datasets/${datasetId}/annotate?${params.toString()}`);
  }

  return (
    <main className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-white/90 backdrop-blur">
        <div className="mx-auto max-w-7xl px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <Link to="/" className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-gray-500 hover:text-gray-900">
              <ArrowLeft size={17} />
              数据集
            </Link>
            <div className="flex items-center gap-2">
              <Link
                to={`/datasets/${datasetId}/triage?queue=untriaged`}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800"
              >
                <ListChecks size={17} />
                快速分拣
              </Link>
              <button
                type="button"
                title="数据集设置"
                onClick={() => setSettingsOpen(true)}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <Settings size={17} />
                设置
              </button>
            </div>
          </div>
          <div className="mt-3 flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold tracking-normal text-ink">{dataset?.name ?? "加载中"}</h1>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-gray-500">{dataset?.description || "暂无数据集说明"}</p>
            </div>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl space-y-5 px-5 py-6">
        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        {dataset && (
          <section className="overflow-hidden rounded-2xl border border-line bg-white shadow-sm" aria-labelledby="dataset-workspace-status">
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1.5fr)_minmax(300px,0.85fr)]">
              <div className="min-w-0 space-y-5 p-5 sm:p-6">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-md bg-gray-900 px-2.5 py-1 text-xs font-semibold text-white">
                    {dataset.task_capabilities.label}
                  </span>
                  <span className="rounded-md border border-line bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-600">
                    Revision {dataset.revision}
                  </span>
                  <span className="text-xs text-gray-500">
                    {dataset.task_capabilities.supported ? "任务能力已启用" : "需要迁移任务类型"}
                  </span>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.16em] text-gray-400">当前工作状态</p>
                  <h2 id="dataset-workspace-status" className="mt-2 text-xl font-semibold text-ink">
                    {workflowPending > 0
                      ? classificationTask
                        ? `还有 ${workflowPending} 个样本待分类`
                        : `还有 ${workflowPending} 张图片待完成`
                      : workflowTotal > 0
                        ? classificationTask ? "样本分类已覆盖当前数据集" : "图片标注已覆盖当前数据集"
                        : "等待扫描样本"}
                  </h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
                    {classificationTask
                      ? "使用样本标签整理类别；对象类别和几何标注不会参与分类完成度。"
                      : geometryTask
                        ? `使用${dataset.task_capabilities.allowed_shape_types.includes("rectangle") ? "矩形框" : "多边形"}标注目标；完成度同时包含有对象图片和已确认无目标图片。`
                        : dataset.task_capabilities.unsupported_reason}
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl bg-gray-50 px-4 py-3">
                    <div className="text-xs text-gray-500">{classificationTask ? "分类完成" : "标注完成"}</div>
                    <div className="mt-1 text-lg font-semibold text-ink">{taskCompletedSamples} / {workflowTotal}</div>
                  </div>
                  <div className="rounded-xl bg-gray-50 px-4 py-3">
                    <div className="text-xs text-gray-500">{uiCopy.reviewStatus}</div>
                    <div className="mt-1 text-lg font-semibold text-ink">{stats?.by_review_status.in_review ?? 0} 待审核</div>
                  </div>
                  <div className="rounded-xl bg-gray-50 px-4 py-3">
                    <div className="text-xs text-gray-500">文件状态</div>
                    <div className={`mt-1 text-lg font-semibold ${unavailableCount > 0 ? "text-red-700" : "text-ink"}`}>
                      {unavailableCount > 0 ? `${unavailableCount} 不可用` : "全部可用"}
                    </div>
                  </div>
                </div>
                <div className="flex min-w-0 items-center gap-2 text-xs text-gray-500">
                  <FolderOpen size={16} className="shrink-0" />
                  <span className="truncate" title={dataset.root_path ?? undefined}>{dataset.root_path || "尚未设置扫描目录"}</span>
                </div>
              </div>
              <div className="min-w-0 border-t border-line bg-gray-50/80 p-5 sm:p-6 lg:border-l lg:border-t-0">
                <p className="text-xs font-medium uppercase tracking-[0.16em] text-gray-400">建议下一步</p>
                <button
                  type="button"
                  onClick={handlePrimaryAction}
                  disabled={scanning || !dataset}
                  className="mt-3 inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
                >
                  {scanning ? <RefreshCw size={18} className="animate-spin" /> : <Play size={18} />}
                  {scanning ? (scanJobId !== null ? "扫描任务运行中" : "兼容扫描中") : primaryActionLabel}
                </button>
                {scanNotice ? (
                  <p aria-live="polite" className="mt-2 text-xs leading-5 text-gray-600">{scanNotice}</p>
                ) : null}
                <div className="mt-5">
                  <div className="flex items-center gap-2 text-sm font-medium text-ink">
                    <ShieldCheck size={17} />
                    关键阻断项
                  </div>
                  {keyBlockers.length === 0 ? (
                    <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs leading-5 text-emerald-800">
                      当前没有发现会阻断主流程的问题。
                    </div>
                  ) : (
                    <div className="mt-3 space-y-2">
                      {keyBlockers.slice(0, 3).map((blocker) => (
                        <div
                          key={blocker.title}
                          className={`rounded-lg border px-3 py-2.5 ${
                            blocker.tone === "danger"
                              ? "border-red-200 bg-red-50 text-red-800"
                              : "border-amber-200 bg-amber-50 text-amber-800"
                          }`}
                        >
                          <div className="text-xs font-semibold">{blocker.title}</div>
                          <div className="mt-1 text-xs leading-5 opacity-80">{blocker.detail}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
        )}

        <div className="grid gap-3 lg:grid-cols-2">
          <details className="group rounded-xl border border-line bg-white shadow-sm">
            <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
              <div>
                <div className="text-sm font-semibold text-ink">数据概览</div>
                <div className="mt-0.5 text-xs text-gray-500">{stats?.sample_count ?? 0} 个样本 · {formatBytes(stats?.total_size ?? 0)}</div>
              </div>
              <ChevronDown size={18} className="shrink-0 text-gray-400 transition group-open:rotate-180" />
            </summary>
            <div className="space-y-4 border-t border-line px-4 py-4">
              {dataset && (
                <div className="grid gap-2 text-sm text-gray-600 sm:grid-cols-2 xl:grid-cols-5">
                  <div className="rounded-lg bg-gray-50 px-3 py-2">项目：{dataset.project || "未设置"}</div>
                  <div className="rounded-lg bg-gray-50 px-3 py-2">负责人：{dataset.owner || "未设置"}</div>
                  <div className="rounded-lg bg-gray-50 px-3 py-2">来源：{dataset.source || "未设置"}</div>
                  <div className="rounded-lg bg-gray-50 px-3 py-2">模态：{dataset.modality || "未设置"}</div>
                  <div className="rounded-lg bg-gray-50 px-3 py-2">许可：{dataset.license || "未设置"}</div>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard label="样本" value={stats?.sample_count ?? 0} icon={<Database size={18} />} actionLabel="全部类型" onClick={() => filterFileType("")} />
                <StatCard label="图片" value={imageCount} icon={<ImageIcon size={18} />} actionLabel="筛选图片" onClick={() => filterFileType("image")} />
                <StatCard label="视频" value={videoCount} icon={<Video size={18} />} actionLabel="筛选视频" onClick={() => filterFileType("video")} />
                <StatCard label={uiCopy.sampleTags} value={tagCount} icon={<Tags size={18} />} tone="info" actionLabel="查看分布" onClick={() => setTagStatsOpen(true)} />
                <StatCard label={classificationTask ? "已分类" : "已标注"} value={taskCompletedSamples} icon={<ClipboardCheck size={18} />} tone={taskCompletedSamples > 0 ? "info" : "neutral"} actionLabel={classificationTask ? `${tagCount} 类别` : `${annotationCount} 对象`} />
                <StatCard label="不可用" value={unavailableCount} icon={<AlertTriangle size={18} />} tone={unavailableCount > 0 ? "danger" : "neutral"} actionLabel={unavailableCount > 0 ? "查看并修复" : undefined} onClick={() => setIssueModal("missing")} />
                <StatCard label="重复" value={duplicateSampleCount} icon={<AlertTriangle size={18} />} tone={duplicateSampleCount > 0 ? "warning" : "neutral"} actionLabel={duplicateSampleCount > 0 ? `${duplicateGroupCount} 组` : undefined} onClick={() => setIssueModal("duplicate")} />
                <StatCard label="容量" value={formatBytes(stats?.total_size ?? 0)} icon={<HardDrive size={18} />} />
              </div>
              <div className="grid gap-3 rounded-lg bg-gray-50 p-3 text-sm sm:grid-cols-4">
                <span>train：{stats?.by_split.train ?? 0}</span>
                <span>val：{stats?.by_split.val ?? 0}</span>
                <span>test：{stats?.by_split.test ?? 0}</span>
                <span>未划分：{stats?.by_split.unassigned ?? 0}</span>
              </div>
              <div className="grid gap-3 rounded-lg border border-line p-3 text-sm lg:grid-cols-[minmax(0,1fr)_minmax(280px,1.2fr)]">
                <div className="flex flex-wrap items-center gap-2 text-gray-600">
                  <span className="font-medium text-ink">{uiCopy.reviewStatus}</span>
                  {([
                    ["not_reviewed", reviewStatusCopy.not_reviewed],
                    ["in_review", reviewStatusCopy.in_review],
                    ["approved", reviewStatusCopy.approved],
                    ["rejected", reviewStatusCopy.rejected]
                  ] as const).map(([status, label]) => (
                    <button key={status} type="button" onClick={() => applyGlobalFilters({ reviewStatus: status })} className="min-h-9 rounded-md border border-line px-2.5 text-xs hover:bg-gray-50">
                      {label} {stats?.by_review_status[status] ?? 0}
                    </button>
                  ))}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-gray-600 lg:justify-end">
                  <span className="font-medium text-ink">{classificationTask ? uiCopy.sampleTags : uiCopy.annotationClasses}</span>
                  {classificationTask && Object.keys(stats?.tag_counts ?? {}).length > 0 ? (
                    Object.entries(stats?.tag_counts ?? {})
                      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
                      .slice(0, 5)
                      .map(([label, count]) => (
                      <button key={label} type="button" onClick={() => applyGlobalFilters({ tag: label })} className="min-h-9 rounded-md border border-line px-2.5 text-xs hover:bg-gray-50">
                        {label} {count}
                      </button>
                      ))
                  ) : !classificationTask && annotationLabelRows.length > 0 ? (
                    annotationLabelRows.map(([label, count]) => (
                      <span key={label} className="rounded-md border border-line px-2.5 py-2 text-xs">
                        {label} {count}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-gray-400">{classificationTask ? "暂无样本标签" : "暂无对象类别"}</span>
                  )}
                </div>
              </div>
              {lastScanResult && (
                <div className="grid gap-2 rounded-lg border border-line p-3 text-sm sm:grid-cols-3 xl:grid-cols-9">
                  <span>扫描 {lastScanResult.scanned}</span>
                  <span>新增 {lastScanResult.imported}</span>
                  <span>变更 {lastScanResult.updated}</span>
                  <span>未变 {lastScanResult.unchanged}</span>
                  <span>缺失 {lastScanResult.missing}</span>
                  <span>计算 hash {lastScanResult.hashed}</span>
                  <span>跳过 hash {lastScanResult.hash_skipped_unchanged}</span>
                  <span>跳过 {lastScanResult.skipped_unsupported}</span>
                  <span>错误 {lastScanResult.error_count}</span>
                </div>
              )}
            </div>
          </details>

          <details className="group rounded-xl border border-line bg-white shadow-sm">
            <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
              <div>
                <div className="text-sm font-semibold text-ink">管理与导出</div>
                <div className="mt-0.5 text-xs text-gray-500">质量、划分、标签、导入与导出</div>
              </div>
              <ChevronDown size={18} className="shrink-0 text-gray-400 transition group-open:rotate-180" />
            </summary>
            <div className="flex flex-wrap gap-2 border-t border-line px-4 py-4">
              <button
                type="button"
                onClick={() => {
                  setTrainingReadiness(null);
                  setTrainingReadinessOpen(true);
                }}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white transition hover:bg-gray-800"
              >
                <ShieldCheck size={17} />
                准备训练
              </button>
              <button
                type="button"
                onClick={() => setSnapshotOpen(true)}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <Camera size={17} />
                数据集快照
              </button>
              <button
                type="button"
                onClick={() => setDirectoryExportOpen(true)}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <FolderOpen size={17} />
                导出分拣目录
              </button>
              <button
                type="button"
                onClick={() => setDirectoryMappingOpen(true)}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <FolderInput size={17} />
                映射旧目录
              </button>
              <DatasetActionMenu
                exportFormat={exportFormat}
                onExportFormatChange={setExportFormat}
                onManageTags={() => setTagsOpen(true)}
                onScan={() => setScanOpen(true)}
                onImportMetadata={() => setMetadataImportOpen(true)}
                onImportLabelme={() => setLabelmeImportOpen(true)}
                onExport={() => void handleExport()}
                onDirectoryExport={() => setDirectoryExportOpen(true)}
                onDirectoryMapping={() => setDirectoryMappingOpen(true)}
                onAnnotationExport={() => setAnnotationExportOpen(true)}
                annotationExportEnabled={geometryTask}
                annotationImportEnabled={geometryTask}
                scanning={scanning}
                annotationExportHint={
                  classificationTask ? "分类整理请使用 CSV 标签表" : dataset?.task_capabilities.unsupported_reason ?? undefined
                }
              />
            </div>
          </details>
        </div>

        <section ref={samplesSectionRef} className="scroll-mt-4 space-y-4" aria-labelledby="sample-workspace-heading">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 id="sample-workspace-heading" className="inline-flex items-center gap-2 text-base font-semibold text-ink">
                <FileText size={18} />
                样本工作区
              </h2>
              <p className="mt-1 text-xs text-gray-500">搜索、筛选、选择并处理当前数据集样本。</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setSavedViewOpen(true)}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <Bookmark size={16} />
                保存视图
              </button>
              {samples.length > 0 && (
                <button
                  type="button"
                  onClick={toggleVisibleSamples}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  {allVisibleSelected ? <CheckSquare size={16} /> : <Square size={16} />}
                  {allVisibleSelected ? "取消本页选择" : "选择本页"}
                </button>
              )}
              <span className="text-sm text-gray-500">{sampleTotal} 项，第 {page} / {pageCount} 页</span>
            </div>
          </div>

          <SearchFilterBar
            search={search}
            fileType={fileType}
            fileStatus={fileStatus}
            tag={tag}
            split={split}
            reviewStatus={reviewStatus}
            annotationProgress={annotationProgress}
            showAnnotationProgress={!classificationTask}
            onSearchChange={setSearch}
            onFileTypeChange={setFileType}
            onFileStatusChange={setFileStatus}
            onTagChange={setTag}
            onSplitChange={setSplit}
            onReviewStatusChange={setReviewStatus}
            onAnnotationProgressChange={setAnnotationProgress}
            onClear={clearFilters}
          />

          <BatchActionBar
            selectedCount={selectedSampleIds.size}
            busy={batchBusy}
            deleting={deletingSamples}
            onApply={handleBatchApply}
            onDelete={handleDeleteSelected}
            onClear={() => setSelectedSampleIds(new Set())}
          />

          <div className="flex flex-col gap-3 rounded-lg border border-line bg-white p-3 shadow-sm lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row">
            <select
              value={sortBy}
              onChange={(event) => {
                setPage(1);
                setSortBy(event.target.value);
              }}
              className="rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900"
            >
              <option value="created_at">创建时间</option>
              <option value="updated_at">更新时间</option>
              <option value="filename">文件名</option>
              <option value="file_size">文件大小</option>
              <option value="file_type">文件类型</option>
              <option value="file_status">文件状态</option>
            </select>
            <select
              value={sortOrder}
              onChange={(event) => {
                setPage(1);
                setSortOrder(event.target.value as "asc" | "desc");
              }}
              className="rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900"
            >
              <option value="desc">降序</option>
              <option value="asc">升序</option>
            </select>
            <select
              value={pageSize}
              onChange={(event) => {
                setPage(1);
                setSamples([]);
                setPageSize(Number(event.target.value));
              }}
              className="rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900"
            >
              <option value={24}>24 / 页</option>
              <option value={60}>60 / 页</option>
              <option value={120}>120 / 页</option>
              <option value={200}>200 / 页</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              title="上一页"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(current - 1, 1))}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              <ChevronLeft size={18} />
            </button>
            <button
              type="button"
              title="下一页"
              disabled={page >= pageCount}
              onClick={() => setPage((current) => Math.min(current + 1, pageCount))}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              <ChevronRight size={18} />
            </button>
          </div>
          </div>

          <SampleGrid
            samples={samples}
            selectedId={selected?.id}
            selectedSampleIds={selectedSampleIds}
            useThumbnails={thumbnailJobsAvailable}
            thumbnailRevision={thumbnailRevision}
            onSelect={handleSelect}
            onToggleSelect={handleToggleSelect}
            onAnnotate={geometryTask ? handleAnnotate : undefined}
          />
        </section>

      <ScanModal
        open={scanOpen}
        defaultPath={dataset?.root_path ?? ""}
        scanning={scanning}
        onClose={() => setScanOpen(false)}
        onScan={handleScan}
      />
      <SampleDetailPanel
        sample={selected}
        availableTags={availableTags}
        saving={saving}
        repairing={repairingSample}
        deleting={deletingSamples}
        onClose={() => setSelected(null)}
        onSave={handleSave}
        onRepair={handleRepairCurrentSample}
        onDelete={handleDeleteCurrentSample}
        onAnnotate={geometryTask ? handleAnnotate : undefined}
      />
      <DatasetSettingsModal
        dataset={dataset}
        open={settingsOpen}
        saving={settingsSaving}
        deleting={deletingDataset}
        onClose={() => setSettingsOpen(false)}
        onSave={handleDatasetSave}
        onDelete={handleDatasetDelete}
      />
      <TagManagerModal
        datasetId={datasetId}
        open={tagsOpen}
        onClose={() => setTagsOpen(false)}
        onChanged={async () => {
          await Promise.all([loadOverview(), loadSamples()]);
        }}
      />
      <TagStatsModal
        open={tagStatsOpen}
        stats={stats}
        tags={availableTags}
        onClose={() => setTagStatsOpen(false)}
        onManage={() => {
          setTagStatsOpen(false);
          setTagsOpen(true);
        }}
        onFilterTag={(tagName) => {
          applyGlobalFilters({ tag: tagName });
          setTagStatsOpen(false);
        }}
        onFilterUnlabeled={() => {
          applyGlobalFilters({ tag: "__untagged__" });
          setTagStatsOpen(false);
        }}
      />
      <MetadataImportModal
        datasetId={datasetId}
        open={metadataImportOpen}
        onClose={() => setMetadataImportOpen(false)}
        onImported={async () => {
          await Promise.all([loadOverview(), loadSamples()]);
        }}
      />
      <LabelmeImportModal
        datasetId={datasetId}
        open={labelmeImportOpen}
        onClose={() => setLabelmeImportOpen(false)}
        onImported={async () => {
          await Promise.all([loadOverview(), loadSamples()]);
        }}
      />
      <MissingRepairModal
        open={missingRepairOpen}
        defaultPath={dataset?.root_path ?? ""}
        repairing={repairingMissing}
        result={missingRepairResult}
        onClose={() => setMissingRepairOpen(false)}
        onRepair={handleRepairMissing}
      />
      <DatasetIssueModal
        datasetId={datasetId}
        issue={issueModal}
        missingCount={missingCount}
        permissionDeniedCount={permissionDeniedCount}
        duplicateGroupCount={duplicateGroupCount}
        duplicateSampleCount={duplicateSampleCount}
        duplicateReport={duplicateReport}
        onClose={() => setIssueModal(null)}
        onFilterMissing={() => filterMissing("missing")}
        onFilterPermissionDenied={() => filterMissing("permission_denied")}
        onFilterDuplicates={filterDuplicates}
        onFilterDuplicateHash={filterDuplicateHash}
        onRepairMissing={openMissingRepair}
      />
      <DatasetQualityModal
        open={qualityOpen}
        taskType={dataset?.task_type}
        report={qualityReport}
        loading={qualityLoading}
        error={qualityError}
        onClose={() => setQualityOpen(false)}
        onRefresh={() => void loadQualityReport()}
        onFilterEmpty={() => {
          if (classificationTask) {
            applyGlobalFilters({ tag: "__untagged__" });
          } else {
            applyGlobalFilters({ fileType: "image", annotationProgress: "not_started" });
          }
          setQualityOpen(false);
        }}
        onFilterReview={(status) => {
          applyGlobalFilters({ fileType: "image", reviewStatus: status });
          setQualityOpen(false);
        }}
        onOpenIssue={(issue) => void openQualityIssue(issue)}
      />
      <TrainingReadinessModal
        datasetId={datasetId}
        open={trainingReadinessOpen}
        report={trainingReadiness}
        loading={trainingReadinessLoading}
        error={trainingReadinessError}
        currentQuery={annotationExportQuery}
        selectedSampleIds={annotationExportSelectedSampleIds}
        onClose={() => setTrainingReadinessOpen(false)}
        onRefresh={() => void loadTrainingReadiness()}
        onShowCompleted={() => {
          applyGlobalFilters(
            classificationTask
              ? { tag: "__tagged__" }
              : { fileType: "image", annotationProgress: "completed_with_objects" }
          );
          setTrainingReadinessOpen(false);
          window.requestAnimationFrame(() => samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
        }}
        onShowEmpty={() => {
          applyGlobalFilters(
            classificationTask
              ? { tag: "__untagged__" }
              : { fileType: "image", annotationProgress: "completed_empty" }
          );
          setTrainingReadinessOpen(false);
          window.requestAnimationFrame(() => samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
        }}
        onShowReview={() => {
          applyGlobalFilters({ fileType: classificationTask ? undefined : "image", reviewStatus: "in_review" });
          setTrainingReadinessOpen(false);
          window.requestAnimationFrame(() => samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
        }}
        onShowSplit={(nextSplit) => {
          applyGlobalFilters({ split: nextSplit });
          setTrainingReadinessOpen(false);
          window.requestAnimationFrame(() => samplesSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
        }}
        onOpenQuality={() => {
          setTrainingReadinessOpen(false);
          setQualityOpen(true);
        }}
        onOpenIssue={(issue) => {
          setTrainingReadinessOpen(false);
          void openQualityIssue(issue);
        }}
        onOpenSplitPlan={() => {
          setTrainingReadinessOpen(false);
          setSplitPlanResult(null);
          setSplitPlanOpen(true);
        }}
        onExportClassification={(trainingConfig) => {
          setTrainingReadinessOpen(false);
          void handleExport("csv", trainingConfig);
        }}
      />
      <SplitPlanModal
        open={splitPlanOpen}
        applying={applyingSplitPlan}
        result={splitPlanResult}
        onClose={() => setSplitPlanOpen(false)}
        onApply={handleApplySplitPlan}
      />
      <ExportPreviewModal
        preview={exportPreview}
        onClose={() => setExportPreview(null)}
        onDownload={handleDownloadExport}
      />
      <AnnotationExportModal
        datasetId={datasetId}
        open={annotationExportOpen}
        defaultFormat={defaultAnnotationExportFormat}
        currentQuery={annotationExportQuery}
        selectedSampleIds={annotationExportSelectedSampleIds}
        onClose={() => setAnnotationExportOpen(false)}
      />
      <DirectoryExportModal
        datasetId={datasetId}
        open={directoryExportOpen}
        currentQuery={annotationExportQuery}
        selectedSampleIds={annotationExportSelectedSampleIds}
        onClose={() => setDirectoryExportOpen(false)}
      />
      <TriageDirectoryMappingModal
        datasetId={datasetId}
        open={directoryMappingOpen}
        onClose={() => setDirectoryMappingOpen(false)}
        onCompleted={() => {
          void Promise.all([loadOverview(), loadSamples()]);
        }}
      />
      <DatasetSnapshotModal
        datasetId={datasetId}
        datasetRevision={dataset?.revision ?? 1}
        open={snapshotOpen}
        sampleQuery={annotationExportQuery}
        exportFormat={exportFormat === "csv" ? "csv" : "manifest"}
        onClose={() => setSnapshotOpen(false)}
      />
      <DatasetSavedViewModal
        datasetId={datasetId}
        currentTaskType={dataset?.task_type ?? "detection"}
        open={savedViewOpen}
        currentQuery={savedViewQuery}
        annotationQueueEnabled={geometryTask}
        onApply={applySavedView}
        onStartQueue={startSavedViewQueue}
        onClose={() => setSavedViewOpen(false)}
      />
      </section>
    </main>
  );
}
