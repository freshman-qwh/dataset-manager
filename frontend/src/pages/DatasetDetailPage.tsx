import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  ClipboardCheck,
  Database,
  FileText,
  FolderOpen,
  HardDrive,
  Image as ImageIcon,
  Play,
  RefreshCw,
  Settings,
  ShieldCheck,
  Square,
  Tags,
  Video
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  applySplitPlan,
  batchUpdateSamples,
  deleteDataset,
  deleteSample,
  deleteSamples,
  getDuplicateReport,
  getDataset,
  getDatasetQualityReport,
  getDatasetStats,
  getExportTemplate,
  getManifestUrl,
  getSample,
  getTrainingReadiness,
  listTags,
  listSamples,
  scanDataset,
  repairMissingSamples,
  repairSample,
  updateDataset,
  updateSample
} from "../api/client";
import AnnotationExportModal from "../components/AnnotationExportModal";
import BatchActionBar from "../components/BatchActionBar";
import DatasetActionMenu from "../components/DatasetActionMenu";
import DatasetIssueModal from "../components/DatasetIssueModal";
import DatasetQualityModal from "../components/DatasetQualityModal";
import DatasetSettingsModal from "../components/DatasetSettingsModal";
import ExportPreviewModal, { type ExportPreview } from "../components/ExportPreviewModal";
import MetadataImportModal from "../components/MetadataImportModal";
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
  TrainingReadinessReport
} from "../types/dataset";
import type { AnnotationExportFormat } from "../types/annotationExport";
import { buildDefaultPendingQueue, buildReviewQueue, readAnnotationQueue } from "../utils/annotationQueue";
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
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [sampleTotal, setSampleTotal] = useState(0);
  const [duplicateReport, setDuplicateReport] = useState<DuplicateReport | null>(null);
  const [qualityReport, setQualityReport] = useState<DatasetQualityReport | null>(null);
  const [availableTags, setAvailableTags] = useState<Tag[]>([]);
  const [selected, setSelected] = useState<Sample | null>(null);
  const [selectedSampleIds, setSelectedSampleIds] = useState<Set<number>>(new Set());
  const [lastScanResult, setLastScanResult] = useState<ScanResult | null>(null);
  const [search, setSearch] = useState("");
  const [fileType, setFileType] = useState("");
  const [fileStatus, setFileStatus] = useState("");
  const [tag, setTag] = useState("");
  const [split, setSplit] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [annotationProgress, setAnnotationProgress] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(60);
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [exportFormat, setExportFormat] = useState("manifest");
  const [scanOpen, setScanOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [tagStatsOpen, setTagStatsOpen] = useState(false);
  const [metadataImportOpen, setMetadataImportOpen] = useState(false);
  const [missingRepairOpen, setMissingRepairOpen] = useState(false);
  const [splitPlanOpen, setSplitPlanOpen] = useState(false);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [trainingReadinessOpen, setTrainingReadinessOpen] = useState(false);
  const [issueModal, setIssueModal] = useState<"missing" | "duplicate" | null>(null);
  const [exportPreview, setExportPreview] = useState<ExportPreview | null>(null);
  const [annotationExportOpen, setAnnotationExportOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
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
  const autoScannedDatasetIds = useRef<Set<number>>(new Set());
  const samplesSectionRef = useRef<HTMLElement | null>(null);
  const debouncedSearch = useDebouncedValue(search);
  const debouncedTag = useDebouncedValue(tag);

  const loadOverview = useCallback(async () => {
    const [nextDataset, nextStats, nextDuplicateReport, nextTags] = await Promise.all([
      getDataset(datasetId),
      getDatasetStats(datasetId),
      getDuplicateReport(datasetId),
      listTags(datasetId)
    ]);
    setDataset(nextDataset);
    setStats(nextStats);
    setDuplicateReport(nextDuplicateReport);
    setAvailableTags(nextTags);
  }, [datasetId]);

  const loadSamples = useCallback(async () => {
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
      sortOrder
    });
    setSamples(nextSamples.items);
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
    setError(null);
    void loadOverview().catch(() => setError("数据集加载失败"));
  }, [datasetId, loadOverview]);

  useEffect(() => {
    if (!Number.isFinite(datasetId)) {
      return;
    }
    void loadSamples().catch(() => setError("样本加载失败"));
  }, [datasetId, loadSamples]);

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
      sort_by: sortBy,
      sort_order: sortOrder
    }),
    [debouncedSearch, debouncedTag, fileStatus, fileType, reviewStatus, sortBy, sortOrder, split]
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

  useEffect(() => {
    if (!dataset?.auto_scan_on_open || !dataset.root_path || autoScannedDatasetIds.current.has(dataset.id)) {
      return;
    }
    autoScannedDatasetIds.current.add(dataset.id);
    setScanning(true);
    setError(null);
    void scanDataset(dataset.id, dataset.root_path)
      .then(async (result) => {
        setLastScanResult(result);
        await Promise.all([loadOverview(), loadSamples()]);
      })
      .catch(() => setError("自动扫描失败，请检查扫描目录是否存在且可读取"))
      .finally(() => setScanning(false));
  }, [dataset, loadOverview, loadSamples]);

  async function handleScan(path: string) {
    setScanning(true);
    setError(null);
    try {
      const result = await scanDataset(datasetId, path);
      setLastScanResult(result);
      await Promise.all([loadOverview(), loadSamples()]);
      setScanOpen(false);
    } catch {
      setError("扫描失败，请检查目录是否存在且可读取");
    } finally {
      setScanning(false);
    }
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

  async function handleExport(formatOverride?: string) {
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
          summary: template.description
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

  function handleDownloadExport() {
    if (!exportPreview) {
      return;
    }
    downloadTextFile(exportPreview.filename, exportPreview.content, exportPreview.mimeType);
    setExportPreview(null);
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
                  {scanning ? "正在扫描" : primaryActionLabel}
                </button>
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
                <div className="grid gap-2 rounded-lg border border-line p-3 text-sm sm:grid-cols-3 xl:grid-cols-7">
                  <span>扫描 {lastScanResult.scanned}</span>
                  <span>新增 {lastScanResult.imported}</span>
                  <span>变更 {lastScanResult.updated}</span>
                  <span>未变 {lastScanResult.unchanged}</span>
                  <span>缺失 {lastScanResult.missing}</span>
                  <span>跳过 {lastScanResult.skipped_unsupported}</span>
                  <span>错误 {lastScanResult.errors.length}</span>
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
              <DatasetActionMenu
                exportFormat={exportFormat}
                onExportFormatChange={setExportFormat}
                onManageTags={() => setTagsOpen(true)}
                onImportMetadata={() => setMetadataImportOpen(true)}
                onExport={() => void handleExport()}
                onAnnotationExport={() => setAnnotationExportOpen(true)}
                annotationExportEnabled={geometryTask}
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
      <MissingRepairModal
        open={missingRepairOpen}
        defaultPath={dataset?.root_path ?? ""}
        repairing={repairingMissing}
        result={missingRepairResult}
        onClose={() => setMissingRepairOpen(false)}
        onRepair={handleRepairMissing}
      />
      <DatasetIssueModal
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
        onExportClassification={() => {
          setTrainingReadinessOpen(false);
          void handleExport("csv");
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
      </section>
    </main>
  );
}
