import { BookOpen, Calendar, Database, Plus, RefreshCw, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createDataset, createIndustrialExample, deleteDataset, listDatasets, updateDataset } from "../api/client";
import CreateDatasetModal from "../components/CreateDatasetModal";
import DatabaseMaintenanceModal from "../components/DatabaseMaintenanceModal";
import DatasetSettingsModal from "../components/DatasetSettingsModal";
import type { Dataset, DatasetCreate } from "../types/dataset";

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(value));
}

export default function DatasetListPage() {
  const navigate = useNavigate();
  const [creatingExample, setCreatingExample] = useState(false);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [settingsDataset, setSettingsDataset] = useState<Dataset | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [deletingDataset, setDeletingDataset] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadDatasets() {
    setLoading(true);
    setError(null);
    try {
      setDatasets(await listDatasets());
    } catch {
      setError("无法连接后端服务");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDatasets();
  }, []);

  async function handleCreate(payload: DatasetCreate) {
    const dataset = await createDataset(payload);
    navigate(`/datasets/${dataset.id}`);
  }

  async function handleSettingsSave(payload: Partial<DatasetCreate>) {
    if (!settingsDataset) {
      return;
    }
    setSavingSettings(true);
    try {
      const updated = await updateDataset(settingsDataset.id, payload);
      setSettingsDataset(updated);
      await loadDatasets();
      setSettingsDataset(null);
    } finally {
      setSavingSettings(false);
    }
  }

  async function handleSettingsDelete() {
    if (!settingsDataset) {
      return;
    }
    setDeletingDataset(true);
    try {
      await deleteDataset(settingsDataset.id);
      setSettingsDataset(null);
      await loadDatasets();
    } finally {
      setDeletingDataset(false);
    }
  }

  return (
    <main className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-5">
          <div>
            <h1 className="text-xl font-semibold tracking-normal text-ink">Dataset Manager</h1>
            <p className="mt-1 text-sm text-gray-500">本地工业数据准备与快速验证</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/library" className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
              <BookOpen size={17} />
              数据集图书馆
            </Link>
            <button
              type="button"
              title="数据库维护"
              aria-label="数据库维护"
              onClick={() => setMaintenanceOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Database size={17} />
              <span className="hidden sm:inline">数据库维护</span>
            </button>
            <button
              type="button"
              onClick={() => setModalOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800"
            >
              <Plus size={17} />
              新建数据集
            </button>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl px-5 py-8">
        <div className="mb-7 rounded-xl border border-line bg-white p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl"><h2 className="text-lg font-semibold text-ink">从本地图片开始，准备可信的异常检测数据</h2><p className="mt-2 text-sm leading-6 text-gray-500">分清正常与异常，按工件隔离数据，再运行基线验证或导出训练包。原始图片保留在本地。</p></div>
            <button type="button" disabled={creatingExample} className="shrink-0 rounded-lg border border-line px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50" onClick={async () => {
              setCreatingExample(true);
              try { const example = await createIndustrialExample(); navigate(`/datasets/${example.id}`); }
              catch { setError("示例创建失败，请检查应用存储和数据库维护状态。"); }
              finally { setCreatingExample(false); }
            }}>{creatingExample ? "正在准备示例…" : "体验合成示例"}</button>
          </div>
          <ol className="mt-5 grid gap-3 border-t border-line pt-4 text-sm text-gray-600 sm:grid-cols-3" aria-label="主要使用流程">
            {["扫描图片并分拣", "确认工件与采集分组", "快速验证或导出训练包"].map((step, index) => <li key={step} className="flex items-center gap-2"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-medium text-gray-600" aria-hidden="true">{index + 1}</span>{step}</li>)}
          </ol>
        </div>
        <div className="mb-4 flex items-center justify-between gap-3"><h2 className="text-base font-semibold text-ink">我的数据集</h2>{!loading && <span className="text-sm text-gray-500">共 {datasets.length} 个</span>}</div>
        {error && <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><span>{error}</span><button type="button" className="underline underline-offset-2" onClick={() => void loadDatasets()}>重新加载</button></div>}

        {loading ? (
          <div className="rounded-lg border border-line bg-white p-8 text-sm text-gray-500 shadow-sm">加载中</div>
        ) : datasets.length === 0 ? (
          <div className="flex min-h-80 flex-col items-center justify-center rounded-lg border border-dashed border-line bg-white px-6 text-center shadow-sm">
            <Database className="text-gray-300" size={40} />
            <h2 className="mt-4 text-base font-semibold text-ink">暂无数据集</h2>
            <p className="mt-2 max-w-sm text-sm leading-6 text-gray-500">先创建数据集，再选择本地图片目录扫描。也可使用上方合成示例熟悉流程。</p>
            <button
              type="button"
              onClick={() => setModalOpen(true)}
              className="mt-5 inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
            >
              <Plus size={17} />
              创建数据集
            </button>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {datasets.map((dataset) => (
              <div
                key={dataset.id}
                className="relative min-w-0 rounded-lg border border-line bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-soft"
              >
                <div className="absolute right-4 top-4">
                  <button
                    type="button"
                    title="数据集设置"
                    aria-label={`${dataset.name}的数据集设置`}
                    onClick={() => setSettingsDataset(dataset)}
                    className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                  >
                    <Settings size={17} />
                  </button>
                </div>
                <Link to={`/datasets/${dataset.id}`} className="block min-w-0 pr-8">
                  <div className="flex flex-col items-start gap-3">
                    <div className="min-w-0 w-full">
                      <h2 title={dataset.name} className="line-clamp-2 break-words text-base font-semibold text-ink">{dataset.name}</h2>
                      <p className="mt-2 line-clamp-2 min-h-10 text-sm text-gray-500">
                        {dataset.description || "未填写描述"}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-md border border-line bg-gray-50 px-2 py-1 text-xs text-gray-600">
                      {dataset.workflow_profile === "industrial_anomaly" ? "工业异常检测" : dataset.task_capabilities.label}
                    </span>
                  </div>
                  <div className="mt-5 flex flex-wrap items-center justify-between gap-2 text-sm text-gray-500">
                    <span className="inline-flex items-center gap-1.5">
                      <Database size={15} />
                      {dataset.sample_count} 样本
                    </span>
                    {dataset.auto_scan_on_open && (
                      <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
                        <RefreshCw size={13} />
                        自动扫描
                      </span>
                    )}
                    <span className="inline-flex items-center gap-1.5">
                      <Calendar size={15} />
                      {formatDate(dataset.created_at)}
                    </span>
                  </div>
                </Link>
              </div>
            ))}
          </div>
        )}
      </section>

      <CreateDatasetModal open={modalOpen} onClose={() => setModalOpen(false)} onCreate={handleCreate} />
      <DatabaseMaintenanceModal open={maintenanceOpen} onClose={() => setMaintenanceOpen(false)} />
      <DatasetSettingsModal
        dataset={settingsDataset}
        open={Boolean(settingsDataset)}
        saving={savingSettings}
        deleting={deletingDataset}
        onClose={() => setSettingsDataset(null)}
        onSave={handleSettingsSave}
        onDelete={handleSettingsDelete}
      />
    </main>
  );
}
