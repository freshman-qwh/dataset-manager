import axios from "axios";
import { BookmarkPlus, ListFilter, Play, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  createDatasetSavedView,
  deleteDatasetSavedView,
  listDatasetSavedViews
} from "../api/client";
import type { AnnotationQueueScope } from "../types/dataset";
import type {
  DatasetSavedView,
  DatasetSavedViewQuery
} from "../types/datasetSavedView";
import { annotationQueueCopy } from "../utils/annotationQueue";
import { annotationProgressCopy, reviewStatusCopy } from "../utils/uiCopy";

interface DatasetSavedViewModalProps {
  datasetId: number;
  currentTaskType: string;
  open: boolean;
  currentQuery: DatasetSavedViewQuery;
  annotationQueueEnabled: boolean;
  onApply: (savedView: DatasetSavedView) => void;
  onStartQueue: (savedView: DatasetSavedView) => void;
  onClose: () => void;
}

const SORT_LABELS: Record<string, string> = {
  created_at: "创建时间",
  updated_at: "更新时间",
  filename: "文件名",
  relative_path: "相对路径",
  file_size: "文件大小",
  extension: "扩展名",
  file_type: "文件类型",
  file_status: "文件状态",
  split: "数据划分",
  review_status: "审核状态",
  annotation_progress: "标注进度"
};

function querySummary(query: DatasetSavedViewQuery): string {
  const parts: string[] = [];
  if (query.search) parts.push(`搜索“${query.search}”`);
  if (query.file_type) parts.push(`类型 ${query.file_type}`);
  if (query.file_status) parts.push(`文件 ${query.file_status}`);
  if (query.tag) parts.push(`标签 ${query.tag}`);
  if (query.split) parts.push(`划分 ${query.split === "unassigned" ? "未划分" : query.split}`);
  if (query.review_status) parts.push(reviewStatusCopy[query.review_status]);
  if (query.annotation_progress) parts.push(annotationProgressCopy[query.annotation_progress]);
  parts.push(`${SORT_LABELS[query.sort_by] ?? query.sort_by}${query.sort_order === "asc" ? "正序" : "倒序"}`);
  return parts.join(" · ");
}

function queueUnavailableReason(
  savedView: DatasetSavedView,
  currentTaskType: string,
  annotationQueueEnabled: boolean
): string | null {
  if (!annotationQueueEnabled) return "当前任务类型不使用几何标注队列";
  if (savedView.task_type !== currentTaskType) return "数据集任务类型已变化，请重新保存此视图";
  if (savedView.queue_scope === "current_split" && !savedView.sample_query.split) {
    return "当前划分队列缺少划分条件";
  }
  if (savedView.queue_scope === "current_filter") {
    if (savedView.sample_query.file_type && savedView.sample_query.file_type !== "image") {
      return "几何标注队列仅支持图片筛选";
    }
    const status = savedView.sample_query.file_status;
    if (status && status !== "normal" && status !== "duplicate") {
      return "不可用文件不能进入标注队列";
    }
  }
  return null;
}

export default function DatasetSavedViewModal({
  datasetId,
  currentTaskType,
  open,
  currentQuery,
  annotationQueueEnabled,
  onApply,
  onStartQueue,
  onClose
}: DatasetSavedViewModalProps) {
  const [name, setName] = useState("");
  const [queueScope, setQueueScope] = useState<AnnotationQueueScope>("current_filter");
  const [savedViews, setSavedViews] = useState<DatasetSavedView[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const currentSummary = useMemo(() => querySummary(currentQuery), [currentQuery]);

  useEffect(() => {
    if (!open) return;
    let disposed = false;
    setLoading(true);
    setError(null);
    setConfirmDeleteId(null);
    void listDatasetSavedViews(datasetId)
      .then((items) => {
        if (!disposed) setSavedViews(items);
      })
      .catch(() => {
        if (!disposed) setError("保存视图读取失败，请确认数据库已升级");
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [datasetId, open]);

  if (!open) return null;

  async function handleCreate() {
    const normalizedName = name.trim();
    if (!normalizedName) {
      setError("请输入视图名称");
      return;
    }
    if (queueScope === "current_split" && !currentQuery.split) {
      setError("当前划分队列需要先选择一个数据划分");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createDatasetSavedView(datasetId, {
        name: normalizedName,
        queue_scope: queueScope,
        sample_query: currentQuery
      });
      setSavedViews((current) => [created, ...current]);
      setName("");
    } catch (caught) {
      if (axios.isAxiosError(caught) && caught.response?.status === 409) {
        setError("同名视图已经存在，请换一个名称");
      } else {
        setError("保存视图失败，请稍后重试");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(savedViewId: number) {
    setDeletingId(savedViewId);
    setError(null);
    try {
      await deleteDatasetSavedView(datasetId, savedViewId);
      setSavedViews((current) => current.filter((item) => item.id !== savedViewId));
      setConfirmDeleteId(null);
    } catch {
      setError("删除保存视图失败，请稍后重试");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-3 sm:p-5">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="saved-view-title"
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-soft"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
          <div>
            <h2 id="saved-view-title" className="text-lg font-semibold text-ink">保存视图与标注队列</h2>
            <p className="mt-1 text-sm text-gray-500">保存筛选和排序，稍后可一键恢复或继续同一标注队列。</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭保存视图" className="rounded-lg p-2 text-gray-500 hover:bg-gray-100">
            <X size={18} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          <div className="rounded-xl border border-line bg-gray-50 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-ink">
              <ListFilter size={16} /> 当前视图
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-gray-500">{currentSummary}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px_auto]">
              <label className="min-w-0">
                <span className="mb-1 block text-xs font-medium text-gray-600">视图名称</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={160}
                  placeholder="例如：train 待审核"
                  className="min-h-11 w-full rounded-lg border border-line bg-white px-3 text-sm outline-none transition focus:border-gray-900"
                />
              </label>
              <label>
                <span className="mb-1 block text-xs font-medium text-gray-600">标注队列范围</span>
                <select
                  value={queueScope}
                  onChange={(event) => setQueueScope(event.target.value as AnnotationQueueScope)}
                  className="min-h-11 w-full rounded-lg border border-line bg-white px-3 text-sm outline-none transition focus:border-gray-900"
                >
                  <option value="current_filter">{annotationQueueCopy.current_filter}</option>
                  <option value="all_pending">{annotationQueueCopy.all_pending}</option>
                  <option value="current_split" disabled={!currentQuery.split}>{annotationQueueCopy.current_split}</option>
                </select>
              </label>
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={saving}
                className="mt-auto inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400"
              >
                <BookmarkPlus size={16} /> {saving ? "保存中" : "保存"}
              </button>
            </div>
          </div>

          {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

          <div className="mt-5">
            <h3 className="text-sm font-semibold text-ink">已保存视图</h3>
            {loading ? (
              <p className="mt-3 text-sm text-gray-500">正在读取…</p>
            ) : savedViews.length === 0 ? (
              <p className="mt-3 rounded-xl border border-dashed border-line px-4 py-6 text-center text-sm text-gray-500">尚未保存视图。</p>
            ) : (
              <div className="mt-3 space-y-3">
                {savedViews.map((savedView) => {
                  const unavailableReason = queueUnavailableReason(savedView, currentTaskType, annotationQueueEnabled);
                  const confirming = confirmDeleteId === savedView.id;
                  return (
                    <article key={savedView.id} className="rounded-xl border border-line p-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h4 className="font-medium text-ink">{savedView.name}</h4>
                            <span className="rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{annotationQueueCopy[savedView.queue_scope]}</span>
                          </div>
                          <p className="mt-2 break-words text-xs leading-5 text-gray-500">{querySummary(savedView.sample_query)}</p>
                          {unavailableReason && <p className="mt-2 text-xs text-amber-700">队列暂不可用：{unavailableReason}</p>}
                        </div>
                        <div className="flex flex-wrap gap-2 sm:justify-end">
                          <button type="button" onClick={() => onApply(savedView)} className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-line px-3 text-sm text-gray-700 hover:bg-gray-50">
                            <RotateCcw size={15} /> 应用视图
                          </button>
                          <button
                            type="button"
                            onClick={() => onStartQueue(savedView)}
                            disabled={Boolean(unavailableReason)}
                            title={unavailableReason ?? undefined}
                            className="inline-flex min-h-10 items-center gap-1.5 rounded-lg bg-gray-900 px-3 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-200 disabled:text-gray-500"
                          >
                            <Play size={15} /> 开始队列
                          </button>
                          {confirming ? (
                            <>
                              <button type="button" onClick={() => void handleDelete(savedView.id)} disabled={deletingId === savedView.id} className="min-h-10 rounded-lg bg-red-600 px-3 text-sm font-medium text-white hover:bg-red-700 disabled:bg-red-300">
                                {deletingId === savedView.id ? "删除中" : "确认删除"}
                              </button>
                              <button type="button" onClick={() => setConfirmDeleteId(null)} className="min-h-10 rounded-lg border border-line px-3 text-sm text-gray-700 hover:bg-gray-50">取消</button>
                            </>
                          ) : (
                            <button type="button" onClick={() => setConfirmDeleteId(savedView.id)} aria-label={`删除视图 ${savedView.name}`} className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-500 hover:bg-red-50 hover:text-red-700">
                              <Trash2 size={15} />
                            </button>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
