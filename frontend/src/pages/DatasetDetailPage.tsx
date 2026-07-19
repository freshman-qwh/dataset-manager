import {
  AlertTriangle,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  ClipboardCheck,
  Database,
  FileText,
  HardDrive,
  Image as ImageIcon,
  RefreshCw,
  Settings,
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
  Tag
} from "../types/dataset";

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
  const [missingRepairResult, setMissingRepairResult] = useState<MissingSampleRepairResult | null>(null);
  const [splitPlanResult, setSplitPlanResult] = useState<SplitPlanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qualityError, setQualityError] = useState<string | null>(null);
  const autoScannedDatasetIds = useRef<Set<number>>(new Set());
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
  const annotatedSamples = stats?.samples_with_objects ?? 0;
  const annotationCount = stats?.annotation_count ?? 0;
  const tagCount = useMemo(() => Object.keys(stats?.tag_counts ?? {}).length, [stats]);
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
    if (qualityOpen && Number.isFinite(datasetId)) {
      void loadQualityReport();
    }
  }, [datasetId, loadQualityReport, qualityOpen]);

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
    const params = new URLSearchParams({
      sample: String(sample.id),
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

  async function handleExport() {
    setError(null);
    try {
      if (exportFormat === "csv") {
        const template = await getExportTemplate(datasetId, exportFormat);
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
    if (issue.code === "FILE_UNAVAILABLE") {
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
        <div className="mx-auto max-w-7xl px-5 py-5">
          <Link to="/" className="inline-flex items-center gap-2 text-sm font-medium text-gray-500 hover:text-gray-900">
            <ArrowLeft size={17} />
            数据集
          </Link>
          <div className="mt-4 flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold tracking-normal text-ink">{dataset?.name ?? "加载中"}</h1>
              <p className="mt-2 max-w-3xl text-sm text-gray-500">{dataset?.description || "未填写描述"}</p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex h-10 min-w-0 overflow-hidden rounded-lg border border-line bg-gray-50 sm:items-stretch">
                <div className="flex min-w-0 flex-1 items-center truncate px-3 text-sm text-gray-600">
                  {dataset?.root_path || "未设置扫描目录"}
                </div>
                <button
                  type="button"
                  title="扫描当前目录"
                  disabled={scanning}
                  onClick={() => {
                    if (dataset?.root_path) {
                      void handleScan(dataset.root_path);
                    } else {
                      setScanOpen(true);
                    }
                  }}
                  className="inline-flex h-full items-center justify-center gap-2 bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
                >
                  <RefreshCw size={16} className={scanning ? "animate-spin" : ""} />
                  {scanning ? "扫描中" : "扫描"}
                </button>
              </div>
              <button
                type="button"
                title="数据集设置"
                onClick={() => setSettingsOpen(true)}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <Settings size={17} />
                设置
              </button>
            </div>
          </div>
          {dataset && (
            <div className="mt-4 grid gap-2 text-sm text-gray-600 sm:grid-cols-2 xl:grid-cols-5">
              <div className="rounded-lg border border-line bg-white px-3 py-2">项目：{dataset.project || "未设置"}</div>
              <div className="rounded-lg border border-line bg-white px-3 py-2">负责人：{dataset.owner || "未设置"}</div>
              <div className="rounded-lg border border-line bg-white px-3 py-2">来源：{dataset.source || "未设置"}</div>
              <div className="rounded-lg border border-line bg-white px-3 py-2">模态：{dataset.modality || "未设置"}</div>
              <div className="rounded-lg border border-line bg-white px-3 py-2">许可：{dataset.license || "未设置"}</div>
            </div>
          )}
        </div>
      </header>

      <section className="mx-auto max-w-7xl space-y-5 px-5 py-6">
        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-8">
          <StatCard
            label="样本"
            value={stats?.sample_count ?? 0}
            icon={<Database size={18} />}
            actionLabel="全部类型"
            onClick={() => filterFileType("")}
          />
          <StatCard
            label="图片"
            value={imageCount}
            icon={<ImageIcon size={18} />}
            actionLabel="筛选图片"
            onClick={() => filterFileType("image")}
          />
          <StatCard
            label="视频"
            value={videoCount}
            icon={<Video size={18} />}
            actionLabel="筛选视频"
            onClick={() => filterFileType("video")}
          />
          <StatCard
            label="标签"
            value={tagCount}
            icon={<Tags size={18} />}
            tone="info"
            actionLabel="查看统计"
            onClick={() => setTagStatsOpen(true)}
          />
          <StatCard
            label="标注"
            value={annotatedSamples}
            icon={<ClipboardCheck size={18} />}
            tone={annotationCount > 0 ? "info" : "neutral"}
            actionLabel={`${annotationCount} 对象`}
          />
          <StatCard
            label="缺失"
            value={unavailableCount}
            icon={<AlertTriangle size={18} />}
            tone={unavailableCount > 0 ? "danger" : "neutral"}
            actionLabel={unavailableCount > 0 ? "查看/修复" : undefined}
            onClick={() => setIssueModal("missing")}
          />
          <StatCard
            label="重复"
            value={duplicateSampleCount}
            icon={<AlertTriangle size={18} />}
            tone={duplicateSampleCount > 0 ? "warning" : "neutral"}
            actionLabel={duplicateSampleCount > 0 ? `${duplicateGroupCount} 组` : undefined}
            onClick={() => setIssueModal("duplicate")}
          />
          <StatCard label="容量" value={formatBytes(stats?.total_size ?? 0)} icon={<HardDrive size={18} />} />
        </div>

        <div className="grid gap-3 rounded-lg border border-line bg-white p-3 text-sm shadow-sm sm:grid-cols-4">
          <span>train：{stats?.by_split.train ?? 0}</span>
          <span>val：{stats?.by_split.val ?? 0}</span>
          <span>test：{stats?.by_split.test ?? 0}</span>
          <span>未划分：{stats?.by_split.unassigned ?? 0}</span>
        </div>

        <div className="grid gap-3 rounded-lg border border-line bg-white p-3 text-sm shadow-sm lg:grid-cols-[minmax(0,1fr)_minmax(280px,1.2fr)]">
          <div className="flex flex-wrap items-center gap-2 text-gray-600">
            <span className="font-medium text-ink">审查状态</span>
            <button type="button" onClick={() => applyGlobalFilters({ reviewStatus: "not_reviewed" })} className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-gray-50">
              未审核 {stats?.by_review_status.not_reviewed ?? 0}
            </button>
            <button type="button" onClick={() => applyGlobalFilters({ reviewStatus: "in_review" })} className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-gray-50">
              待审核 {stats?.by_review_status.in_review ?? 0}
            </button>
            <button type="button" onClick={() => applyGlobalFilters({ reviewStatus: "approved" })} className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-gray-50">
              已通过 {stats?.by_review_status.approved ?? 0}
            </button>
            <button type="button" onClick={() => applyGlobalFilters({ reviewStatus: "rejected" })} className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-gray-50">
              已拒绝 {stats?.by_review_status.rejected ?? 0}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-gray-600 lg:justify-end">
            <span className="font-medium text-ink">标注类别</span>
            {annotationLabelRows.length > 0 ? (
              annotationLabelRows.map(([label, count]) => (
                <button key={label} type="button" onClick={() => applyGlobalFilters({ tag: label })} className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-gray-50">
                  {label} {count}
                </button>
              ))
            ) : (
              <span className="text-xs text-gray-400">暂无对象类别</span>
            )}
          </div>
        </div>

        {lastScanResult && (
          <div className="grid gap-2 rounded-lg border border-line bg-white p-3 text-sm shadow-sm sm:grid-cols-3 xl:grid-cols-7">
            <span>扫描 {lastScanResult.scanned}</span>
            <span>新增 {lastScanResult.imported}</span>
            <span>变更 {lastScanResult.updated}</span>
            <span>未变 {lastScanResult.unchanged}</span>
            <span>缺失 {lastScanResult.missing}</span>
            <span>跳过 {lastScanResult.skipped_unsupported}</span>
            <span>错误 {lastScanResult.errors.length}</span>
          </div>
        )}

        <SearchFilterBar
          search={search}
          fileType={fileType}
          fileStatus={fileStatus}
          tag={tag}
          split={split}
          reviewStatus={reviewStatus}
          annotationProgress={annotationProgress}
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

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <FileText size={18} />
            样本
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            {samples.length > 0 && (
              <button
                type="button"
                onClick={toggleVisibleSamples}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                {allVisibleSelected ? <CheckSquare size={16} /> : <Square size={16} />}
                {allVisibleSelected ? "取消本页" : "选择本页"}
              </button>
            )}
            <button
              type="button"
              onClick={() => setQualityOpen(true)}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <ClipboardCheck size={16} />
              数据健康
            </button>
            <button
              type="button"
              onClick={() => {
                setSplitPlanResult(null);
                setSplitPlanOpen(true);
              }}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <FileText size={16} />
              划分
            </button>
            <DatasetActionMenu
              exportFormat={exportFormat}
              onExportFormatChange={setExportFormat}
              onManageTags={() => setTagsOpen(true)}
              onImportMetadata={() => setMetadataImportOpen(true)}
              onExport={() => void handleExport()}
              onAnnotationExport={() => setAnnotationExportOpen(true)}
            />
            <span className="text-sm text-gray-500">
              {sampleTotal} 项，第 {page} / {pageCount} 页
            </span>
          </div>
        </div>

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
          onAnnotate={handleAnnotate}
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
        onAnnotate={handleAnnotate}
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
        report={qualityReport}
        loading={qualityLoading}
        error={qualityError}
        onClose={() => setQualityOpen(false)}
        onRefresh={() => void loadQualityReport()}
        onFilterEmpty={() => {
          applyGlobalFilters({ fileType: "image", annotationProgress: "not_started" });
          setQualityOpen(false);
        }}
        onFilterReview={(status) => {
          applyGlobalFilters({ fileType: "image", reviewStatus: status });
          setQualityOpen(false);
        }}
        onOpenIssue={(issue) => void openQualityIssue(issue)}
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
        currentQuery={annotationExportQuery}
        selectedSampleIds={annotationExportSelectedSampleIds}
        onClose={() => setAnnotationExportOpen(false)}
      />
    </main>
  );
}
