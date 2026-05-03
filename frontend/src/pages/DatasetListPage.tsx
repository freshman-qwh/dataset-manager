import { Calendar, Database, MoreHorizontal, Plus, RefreshCw, Settings, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { createDataset, deleteDataset, listDatasets, updateDataset } from "../api/client";
import CreateDatasetModal from "../components/CreateDatasetModal";
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
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [settingsDataset, setSettingsDataset] = useState<Dataset | null>(null);
  const [menuDatasetId, setMenuDatasetId] = useState<number | null>(null);
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
    await createDataset(payload);
    await loadDatasets();
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
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-5">
          <div>
            <h1 className="text-xl font-semibold tracking-normal text-ink">Dataset Manager</h1>
            <p className="mt-1 text-sm text-gray-500">本地科研数据集工作台</p>
          </div>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800"
          >
            <Plus size={17} />
            新建
          </button>
        </div>
      </header>

      <section className="mx-auto max-w-7xl px-5 py-8">
        {error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        {loading ? (
          <div className="rounded-lg border border-line bg-white p-8 text-sm text-gray-500 shadow-sm">加载中</div>
        ) : datasets.length === 0 ? (
          <div className="flex min-h-80 flex-col items-center justify-center rounded-lg border border-dashed border-line bg-white px-6 text-center shadow-sm">
            <Database className="text-gray-300" size={40} />
            <h2 className="mt-4 text-base font-semibold text-ink">暂无数据集</h2>
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
                className="relative rounded-lg border border-line bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-soft"
              >
                <div className="absolute right-4 top-4">
                  <button
                    type="button"
                    title="数据集操作"
                    onClick={() => setMenuDatasetId((current) => (current === dataset.id ? null : dataset.id))}
                    className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                  >
                    <MoreHorizontal size={17} />
                  </button>
                  {menuDatasetId === dataset.id && (
                    <div className="absolute right-0 z-20 mt-2 w-40 rounded-lg border border-line bg-white p-1 shadow-soft">
                      <button
                        type="button"
                        onClick={() => {
                          setSettingsDataset(dataset);
                          setMenuDatasetId(null);
                        }}
                        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                      >
                        <Settings size={15} />
                        设置
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSettingsDataset(dataset);
                          setMenuDatasetId(null);
                        }}
                        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
                      >
                        <Trash2 size={15} />
                        删除元数据
                      </button>
                    </div>
                  )}
                </div>
                <Link to={`/datasets/${dataset.id}`} className="block pr-8">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h2 className="truncate text-base font-semibold text-ink">{dataset.name}</h2>
                      <p className="mt-2 line-clamp-2 min-h-10 text-sm text-gray-500">
                        {dataset.description || "未填写描述"}
                      </p>
                    </div>
                    <span className="rounded-md border border-line bg-gray-50 px-2 py-1 text-xs text-gray-600">
                      {dataset.task_type || "other"}
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
