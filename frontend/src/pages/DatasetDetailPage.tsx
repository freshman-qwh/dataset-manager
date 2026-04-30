import {
  AlertTriangle,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Database,
  FileText,
  HardDrive,
  Image as ImageIcon,
  Settings,
  Tags,
  Video
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  batchUpdateSamples,
  deleteDataset,
  getDuplicateReport,
  getDataset,
  getDatasetStats,
  getExportTemplate,
  getManifestUrl,
  getSample,
  listTags,
  listSamples,
  scanDataset,
  updateDataset,
  updateSample
} from "../api/client";
import BatchActionBar from "../components/BatchActionBar";
import DatasetSettingsModal from "../components/DatasetSettingsModal";
import ExportPreviewModal, { type ExportPreview } from "../components/ExportPreviewModal";
import MetadataImportModal from "../components/MetadataImportModal";
import SampleDetailPanel from "../components/SampleDetailPanel";
import SampleGrid from "../components/SampleGrid";
import ScanModal from "../components/ScanModal";
import SearchFilterBar from "../components/SearchFilterBar";
import StatCard from "../components/StatCard";
import TagManagerModal from "../components/TagManagerModal";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type { Dataset, DatasetStats, DuplicateReport, Sample, ScanResult, Tag } from "../types/dataset";

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
  const [availableTags, setAvailableTags] = useState<Tag[]>([]);
  const [selected, setSelected] = useState<Sample | null>(null);
  const [selectedSampleIds, setSelectedSampleIds] = useState<Set<number>>(new Set());
  const [lastScanResult, setLastScanResult] = useState<ScanResult | null>(null);
  const [search, setSearch] = useState("");
  const [fileType, setFileType] = useState("");
  const [tag, setTag] = useState("");
  const [split, setSplit] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(60);
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [exportFormat, setExportFormat] = useState("manifest");
  const [scanOpen, setScanOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [metadataImportOpen, setMetadataImportOpen] = useState(false);
  const [exportPreview, setExportPreview] = useState<ExportPreview | null>(null);
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [deletingDataset, setDeletingDataset] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      tag: debouncedTag,
      split,
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
  }, [datasetId, debouncedSearch, debouncedTag, fileType, split, page, pageSize, sortBy, sortOrder]);

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
  const duplicateSampleCount = stats?.duplicate_samples ?? 0;
  const tagCount = useMemo(() => Object.keys(stats?.tag_counts ?? {}).length, [stats]);
  const pageCount = Math.max(Math.ceil(sampleTotal / pageSize), 1);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, debouncedTag, fileType, split, sortBy, sortOrder]);

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

  async function handleExport() {
    setError(null);
    try {
      if (exportFormat !== "manifest") {
        const template = await getExportTemplate(datasetId, exportFormat);
        if (exportFormat === "csv") {
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
        const formatTitle = exportFormat === "coco" ? "COCO 骨架" : "YOLO 骨架";
        setExportPreview({
          title: formatTitle,
          filename: `dataset-${datasetId}-${exportFormat}-template.json`,
          mimeType: "application/json;charset=utf-8",
          content: `${JSON.stringify(template.payload, null, 2)}\n`,
          summary: template.description
        });
        return;
      }
      const response = await fetch(
        getManifestUrl(datasetId, {
          search: debouncedSearch,
          fileType,
          tag: debouncedTag,
          split,
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
              <div className="rounded-lg border border-line bg-gray-50 px-3 py-2 text-sm text-gray-600">
                {dataset?.root_path || "未设置扫描目录"}
              </div>
              <button
                type="button"
                title="数据集设置"
                onClick={() => setSettingsOpen(true)}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
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

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-7">
          <StatCard label="样本" value={stats?.sample_count ?? 0} icon={<Database size={18} />} />
          <StatCard label="图片" value={imageCount} icon={<ImageIcon size={18} />} />
          <StatCard label="视频" value={videoCount} icon={<Video size={18} />} />
          <StatCard label="标签" value={tagCount} icon={<Tags size={18} />} />
          <StatCard label="缺失" value={missingCount} icon={<AlertTriangle size={18} />} />
          <StatCard label="重复" value={duplicateSampleCount} icon={<AlertTriangle size={18} />} />
          <StatCard label="容量" value={formatBytes(stats?.total_size ?? 0)} icon={<HardDrive size={18} />} />
        </div>

        <div className="grid gap-3 rounded-lg border border-line bg-white p-3 text-sm shadow-sm sm:grid-cols-4">
          <span>train：{stats?.by_split.train ?? 0}</span>
          <span>val：{stats?.by_split.val ?? 0}</span>
          <span>test：{stats?.by_split.test ?? 0}</span>
          <span>未划分：{stats?.by_split.unassigned ?? 0}</span>
        </div>

        {duplicateReport && duplicateReport.group_count > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <div className="font-medium">
              发现 {duplicateReport.group_count} 组重复样本，共 {duplicateReport.duplicate_sample_count} 个样本
            </div>
            <div className="mt-2 space-y-1">
              {duplicateReport.groups.slice(0, 3).map((group) => (
                <div key={group.file_hash} className="truncate">
                  {group.file_hash.slice(0, 12)}...：{group.samples.map((sample) => sample.relative_path).join(" / ")}
                </div>
              ))}
            </div>
          </div>
        )}

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
          tag={tag}
          split={split}
          exportFormat={exportFormat}
          onSearchChange={setSearch}
          onFileTypeChange={setFileType}
          onTagChange={setTag}
          onSplitChange={setSplit}
          onExportFormatChange={setExportFormat}
          onScan={() => setScanOpen(true)}
          onImportMetadata={() => setMetadataImportOpen(true)}
          onManageTags={() => setTagsOpen(true)}
          onExport={() => void handleExport()}
        />

        <BatchActionBar
          selectedCount={selectedSampleIds.size}
          busy={batchBusy}
          onApply={handleBatchApply}
          onClear={() => setSelectedSampleIds(new Set())}
        />

        <div className="flex items-center justify-between">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <FileText size={18} />
            样本
          </h2>
          <span className="text-sm text-gray-500">
            {sampleTotal} 项，第 {page} / {pageCount} 页
          </span>
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
        onClose={() => setSelected(null)}
        onSave={handleSave}
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
      <MetadataImportModal
        datasetId={datasetId}
        open={metadataImportOpen}
        onClose={() => setMetadataImportOpen(false)}
        onImported={async () => {
          await Promise.all([loadOverview(), loadSamples()]);
        }}
      />
      <ExportPreviewModal
        preview={exportPreview}
        onClose={() => setExportPreview(null)}
        onDownload={handleDownloadExport}
      />
    </main>
  );
}
