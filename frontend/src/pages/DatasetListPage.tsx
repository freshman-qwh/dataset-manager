import { Calendar, Database, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { createDataset, listDatasets } from "../api/client";
import CreateDatasetModal from "../components/CreateDatasetModal";
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
              <Link
                key={dataset.id}
                to={`/datasets/${dataset.id}`}
                className="rounded-lg border border-line bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-soft"
              >
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
                <div className="mt-5 flex items-center justify-between text-sm text-gray-500">
                  <span className="inline-flex items-center gap-1.5">
                    <Database size={15} />
                    {dataset.sample_count} 样本
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <Calendar size={15} />
                    {formatDate(dataset.created_at)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <CreateDatasetModal open={modalOpen} onClose={() => setModalOpen(false)} onCreate={handleCreate} />
    </main>
  );
}
