import axios from "axios";
import { Camera, Download, Eye, GitCompare, LoaderCircle, RefreshCw } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createDatasetSnapshot,
  compareDatasetSnapshots,
  getDatasetSnapshotDownloadUrl,
  getDatasetSnapshotTrainingLabelsDownloadUrl,
  listDatasetSnapshots,
  readDatasetSnapshot,
  rebuildDatasetSnapshotTrainingLabels
} from "../api/client";
import type { AnnotationExportSampleQuery } from "../types/annotationExport";
import type {
  DatasetSnapshot,
  DatasetSnapshotDiffResponse,
  DatasetSnapshotDocument,
  DatasetSnapshotExportFormat,
  DatasetSnapshotTrainingLabels
} from "../types/datasetSnapshot";
import Modal from "./Modal";

interface DatasetSnapshotModalProps {
  datasetId: number;
  datasetRevision: number;
  open: boolean;
  sampleQuery: AnnotationExportSampleQuery;
  exportFormat: DatasetSnapshotExportFormat;
  onClose: () => void;
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && typeof error.response?.data?.detail === "string") {
    return error.response.data.detail;
  }
  return "快照操作失败，请确认后端服务和数据库迁移状态后重试。";
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

export default function DatasetSnapshotModal({
  datasetId,
  datasetRevision,
  open,
  sampleQuery,
  exportFormat,
  onClose
}: DatasetSnapshotModalProps) {
  const [name, setName] = useState("");
  const [snapshots, setSnapshots] = useState<DatasetSnapshot[]>([]);
  const [selected, setSelected] = useState<DatasetSnapshotDocument | null>(null);
  const [diff, setDiff] = useState<DatasetSnapshotDiffResponse | null>(null);
  const [trainingLabels, setTrainingLabels] = useState<DatasetSnapshotTrainingLabels | null>(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [readingId, setReadingId] = useState<number | null>(null);
  const [comparingId, setComparingId] = useState<number | null>(null);
  const [rebuildingId, setRebuildingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSnapshots = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSnapshots(await listDatasetSnapshots(datasetId));
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }, [datasetId]);

  useEffect(() => {
    if (!open) return;
    setSelected(null);
    setDiff(null);
    setTrainingLabels(null);
    void loadSnapshots();
  }, [loadSnapshots, open]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await createDatasetSnapshot(datasetId, {
        name: name.trim() || null,
        sample_query: sampleQuery,
        export_config: {
          format: exportFormat,
          include_empty: true,
          class_map: []
        }
      });
      setName("");
      await loadSnapshots();
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setCreating(false);
    }
  }

  async function handleRead(snapshotId: number) {
    setReadingId(snapshotId);
    setError(null);
    try {
      setSelected(await readDatasetSnapshot(datasetId, snapshotId));
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setReadingId(null);
    }
  }

  async function handleCompare(baseSnapshotId: number, targetSnapshotId: number) {
    setComparingId(targetSnapshotId);
    setError(null);
    try {
      setDiff(await compareDatasetSnapshots(datasetId, baseSnapshotId, targetSnapshotId));
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setComparingId(null);
    }
  }

  async function handleRebuild(snapshotId: number) {
    setRebuildingId(snapshotId);
    setError(null);
    try {
      setTrainingLabels(await rebuildDatasetSnapshotTrainingLabels(datasetId, snapshotId));
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setRebuildingId(null);
    }
  }

  return (
    <Modal open={open} title="数据集快照" onClose={onClose} size="lg">
      <div className="max-h-[78vh] space-y-5 overflow-y-auto p-5">
        <div className="rounded-xl border border-line bg-gray-50 p-4 text-sm text-gray-600">
          快照冻结当前筛选范围、文件 hash、标签、划分与标注元数据。它不会复制或修改原始文件。
          当前数据集为 Revision {datasetRevision}。
        </div>

        <form onSubmit={handleCreate} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="min-w-0 flex-1 text-sm font-medium text-gray-700">
            快照名称（可选）
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={160}
              placeholder={`Revision ${datasetRevision}`}
              className="mt-2 min-h-11 w-full rounded-lg border border-line bg-white px-3 outline-none focus:border-gray-900"
            />
          </label>
          <button
            type="submit"
            disabled={creating}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {creating ? <LoaderCircle size={17} className="animate-spin" /> : <Camera size={17} />}
            {creating ? "正在创建" : "创建当前视图快照"}
          </button>
        </form>

        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <section aria-label="快照列表">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">历史快照</h3>
            <span className="text-xs text-gray-500">{snapshots.length} 项</span>
          </div>
          {loading ? (
            <div className="flex min-h-24 items-center justify-center text-sm text-gray-500">
              <LoaderCircle size={17} className="mr-2 animate-spin" />加载中
            </div>
          ) : snapshots.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-gray-500">
              暂无快照
            </div>
          ) : (
            <div className="space-y-2">
              {snapshots.map((snapshot, index) => (
                <article key={snapshot.id} className="rounded-xl border border-line p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-ink">{snapshot.name || `快照 #${snapshot.id}`}</span>
                        <span className="rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-600">Revision {snapshot.dataset_revision}</span>
                      </div>
                      <p className="mt-2 text-xs text-gray-500">
                        {formatTime(snapshot.created_at)} · {snapshot.sample_count} 样本 · {snapshot.annotation_count} 标注 · SHA-256 {snapshot.content_sha256.slice(0, 12)}…
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      {index < snapshots.length - 1 && (
                        <button
                          type="button"
                          onClick={() => void handleCompare(snapshots[index + 1].id, snapshot.id)}
                          disabled={comparingId === snapshot.id}
                          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm text-gray-700 hover:bg-gray-50 disabled:text-gray-300"
                        >
                          {comparingId === snapshot.id ? <LoaderCircle size={16} className="animate-spin" /> : <GitCompare size={16} />}
                          比较
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void handleRead(snapshot.id)}
                        disabled={readingId === snapshot.id}
                        className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm text-gray-700 hover:bg-gray-50 disabled:text-gray-300"
                      >
                        {readingId === snapshot.id ? <LoaderCircle size={16} className="animate-spin" /> : <Eye size={16} />}
                        查看
                      </button>
                      <a
                        href={getDatasetSnapshotDownloadUrl(datasetId, snapshot.id)}
                        className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm text-gray-700 hover:bg-gray-50"
                      >
                        <Download size={16} />下载
                      </a>
                      <button
                        type="button"
                        onClick={() => void handleRebuild(snapshot.id)}
                        disabled={rebuildingId === snapshot.id}
                        className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm text-gray-700 hover:bg-gray-50 disabled:text-gray-300"
                      >
                        {rebuildingId === snapshot.id ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                        重建标签
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        {selected && (
          <section className="rounded-xl border border-line bg-gray-50 p-4" aria-label="快照内容摘要">
            <h3 className="text-sm font-semibold text-ink">快照内容摘要</h3>
            <div className="mt-3 grid gap-2 text-sm text-gray-600 sm:grid-cols-2">
              <span>Revision {selected.dataset_revision}</span>
              <span>结构版本 {selected.content.schema_version}</span>
              <span>{selected.content.sample_count} 个样本</span>
              <span>{selected.content.annotation_count} 个标注</span>
              <span>{selected.content.class_map.length} 个类别映射</span>
              <span className="truncate" title={selected.content_sha256}>SHA-256 {selected.content_sha256}</span>
            </div>
          </section>
        )}

        {diff && (
          <section className="rounded-xl border border-line bg-gray-50 p-4" aria-label="快照差异摘要">
            <h3 className="text-sm font-semibold text-ink">快照差异摘要</h3>
            <p className="mt-1 text-xs text-gray-500">Revision {diff.base_revision} → {diff.target_revision}</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-gray-600 sm:grid-cols-4">
              <span>新增 {diff.summary.added}</span>
              <span>删除 {diff.summary.removed}</span>
              <span>文件 {diff.summary.file_changed}</span>
              <span>元数据 {diff.summary.metadata_changed}</span>
              <span>标签 {diff.summary.tags_changed}</span>
              <span>划分 {diff.summary.split_changed}</span>
              <span>标注 {diff.summary.annotations_changed}</span>
              <span>变化样本 {diff.summary.changed_samples}</span>
            </div>
            {diff.items.length > 0 && (
              <div className="mt-3 max-h-36 space-y-1 overflow-y-auto border-t border-line pt-3 text-xs text-gray-600">
                {diff.items.slice(0, 20).map((item) => (
                  <div key={item.sample_id} className="flex justify-between gap-3">
                    <span className="min-w-0 truncate">{item.relative_path}</span>
                    <span className="shrink-0">{item.change_types.join(" / ")}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {trainingLabels && (
          <section className="rounded-xl border border-line bg-gray-50 p-4" aria-label="训练标签重建摘要">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-ink">训练标签已重建</h3>
                <p className="mt-2 text-xs text-gray-500">
                  {trainingLabels.format} · {trainingLabels.sample_count} 样本 · SHA-256 {trainingLabels.label_sha256}
                </p>
              </div>
              <a
                href={getDatasetSnapshotTrainingLabelsDownloadUrl(datasetId, trainingLabels.snapshot_id)}
                className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 text-sm text-gray-700 hover:bg-gray-50"
              >
                <Download size={16} />下载标签
              </a>
            </div>
          </section>
        )}
      </div>
    </Modal>
  );
}
