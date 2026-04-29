import { ArrowLeft, Database, FileText, HardDrive, Image as ImageIcon, Tags, Video } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getDataset,
  getDatasetStats,
  getManifestUrl,
  getSample,
  listSamples,
  scanDataset,
  updateSample
} from "../api/client";
import SampleDetailPanel from "../components/SampleDetailPanel";
import SampleGrid from "../components/SampleGrid";
import ScanModal from "../components/ScanModal";
import SearchFilterBar from "../components/SearchFilterBar";
import StatCard from "../components/StatCard";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type { Dataset, DatasetStats, Sample } from "../types/dataset";

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

export default function DatasetDetailPage() {
  const params = useParams();
  const datasetId = Number(params.datasetId);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [selected, setSelected] = useState<Sample | null>(null);
  const [search, setSearch] = useState("");
  const [fileType, setFileType] = useState("");
  const [tag, setTag] = useState("");
  const [scanOpen, setScanOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debouncedSearch = useDebouncedValue(search);
  const debouncedTag = useDebouncedValue(tag);

  const loadOverview = useCallback(async () => {
    const [nextDataset, nextStats] = await Promise.all([getDataset(datasetId), getDatasetStats(datasetId)]);
    setDataset(nextDataset);
    setStats(nextStats);
  }, [datasetId]);

  const loadSamples = useCallback(async () => {
    const nextSamples = await listSamples({
      datasetId,
      search: debouncedSearch,
      fileType,
      tag: debouncedTag
    });
    setSamples(nextSamples);
  }, [datasetId, debouncedSearch, debouncedTag, fileType]);

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
  const tagCount = useMemo(() => Object.keys(stats?.tag_counts ?? {}).length, [stats]);

  async function handleScan(path: string) {
    setScanning(true);
    setError(null);
    try {
      await scanDataset(datasetId, path);
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

  function handleExport() {
    window.open(getManifestUrl(datasetId), "_blank", "noopener,noreferrer");
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
            <div className="rounded-lg border border-line bg-gray-50 px-3 py-2 text-sm text-gray-600">
              {dataset?.root_path || "未设置扫描目录"}
            </div>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl space-y-5 px-5 py-6">
        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <StatCard label="样本" value={stats?.sample_count ?? 0} icon={<Database size={18} />} />
          <StatCard label="图片" value={imageCount} icon={<ImageIcon size={18} />} />
          <StatCard label="视频" value={videoCount} icon={<Video size={18} />} />
          <StatCard label="标签" value={tagCount} icon={<Tags size={18} />} />
          <StatCard label="容量" value={formatBytes(stats?.total_size ?? 0)} icon={<HardDrive size={18} />} />
        </div>

        <SearchFilterBar
          search={search}
          fileType={fileType}
          tag={tag}
          onSearchChange={setSearch}
          onFileTypeChange={setFileType}
          onTagChange={setTag}
          onScan={() => setScanOpen(true)}
          onExport={handleExport}
        />

        <div className="flex items-center justify-between">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <FileText size={18} />
            样本
          </h2>
          <span className="text-sm text-gray-500">{samples.length} 项</span>
        </div>

        <SampleGrid samples={samples} selectedId={selected?.id} onSelect={handleSelect} />
      </section>

      <ScanModal
        open={scanOpen}
        defaultPath={dataset?.root_path ?? ""}
        scanning={scanning}
        onClose={() => setScanOpen(false)}
        onScan={handleScan}
      />
      <SampleDetailPanel sample={selected} saving={saving} onClose={() => setSelected(null)} onSave={handleSave} />
    </main>
  );
}
