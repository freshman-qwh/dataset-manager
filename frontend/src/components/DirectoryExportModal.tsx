import axios from "axios";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  FolderOpen,
  LoaderCircle,
  SearchCheck
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  createDirectoryExportJob,
  createDirectoryExportPreview,
  downloadJobArtifact,
  getDirectoryExportPreview,
  getJob
} from "../api/client";
import type {
  DirectoryExportDelivery,
  DirectoryExportPreviewResponse,
  DirectoryExportSampleQuery
} from "../types/directoryExport";
import type { Job } from "../types/job";
import Modal from "./Modal";


type ExportScope = "filtered" | "all" | "split" | "selected";

interface DirectoryExportModalProps {
  datasetId: number;
  open: boolean;
  currentQuery: DirectoryExportSampleQuery;
  selectedSampleIds: number[];
  onClose: () => void;
}

const EXCLUSION_LABELS: Record<string, string> = {
  pending_excluded: "待定未纳入",
  untriaged_excluded: "未分拣未纳入",
  triage_outdated: "判定已过期",
  file_unavailable: "文件不可用",
  source_missing: "源文件缺失",
  source_unreadable: "源文件不可读",
  status_not_exportable: "状态不可导出"
};

const STAGE_LABELS: Record<string, string> = {
  queued: "等待执行",
  starting: "准备任务",
  copying_files: "复制并校验图片",
  finalizing: "生成清单并校验 ZIP",
  publishing_directory: "发布服务器目录",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  process_stopped: "已中断"
};

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MiB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GiB`;
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function DirectoryExportModal({
  datasetId,
  open,
  currentQuery,
  selectedSampleIds,
  onClose
}: DirectoryExportModalProps) {
  const [scope, setScope] = useState<ExportScope>("filtered");
  const [selectedSplit, setSelectedSplit] = useState("train");
  const [delivery, setDelivery] = useState<DirectoryExportDelivery>("zip");
  const [runName, setRunName] = useState("");
  const [includePending, setIncludePending] = useState(false);
  const [includeUntriaged, setIncludeUntriaged] = useState(false);
  const [includeOutdated, setIncludeOutdated] = useState(false);
  const [preview, setPreview] = useState<DirectoryExportPreviewResponse | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [checking, setChecking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [paging, setPaging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sampleQuery = useMemo<DirectoryExportSampleQuery>(() => {
    if (scope === "all") return { sort_by: "relative_path", sort_order: "asc" };
    if (scope === "split") {
      return { split: selectedSplit, sort_by: "relative_path", sort_order: "asc" };
    }
    if (scope === "selected") {
      return { sample_ids: selectedSampleIds, sort_by: "relative_path", sort_order: "asc" };
    }
    return { ...currentQuery, sort_by: "relative_path", sort_order: "asc" };
  }, [currentQuery, scope, selectedSampleIds, selectedSplit]);

  const requestKey = JSON.stringify({
    sampleQuery,
    delivery,
    runName,
    includePending,
    includeUntriaged,
    includeOutdated
  });

  useEffect(() => {
    setPreview(null);
    setJob(null);
    setError(null);
  }, [requestKey]);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setJob(null);
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let disposed = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const current = await getJob(job.id);
        if (disposed) return;
        setJob(current);
        if (["queued", "running"].includes(current.status)) {
          timer = window.setTimeout(() => void poll(), 750);
        }
      } catch (caught) {
        if (!disposed) setError(errorMessage(caught));
      }
    };
    void poll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [job?.id, job?.status]);

  async function runPreview() {
    if (scope === "selected" && selectedSampleIds.length === 0) {
      setError("请先选择至少一个样本。");
      return;
    }
    setChecking(true);
    setError(null);
    setJob(null);
    try {
      const result = await createDirectoryExportPreview(datasetId, {
        delivery,
        sample_query: sampleQuery,
        include_pending: includePending,
        include_untriaged: includeUntriaged,
        include_outdated: includeOutdated,
        run_name: runName.trim() || undefined
      });
      setPreview(result);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setChecking(false);
    }
  }

  async function changePage(page: number) {
    if (!preview || paging) return;
    setPaging(true);
    setError(null);
    try {
      setPreview(await getDirectoryExportPreview(datasetId, preview.plan_id, page, preview.page_size));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPaging(false);
    }
  }

  async function submitOrDownload() {
    if (!preview || preview.blocked) return;
    setSubmitting(true);
    setError(null);
    try {
      if (job?.status === "succeeded" && delivery === "zip") {
        const result = await downloadJobArtifact(job.id);
        triggerDownload(result.blob, result.filename);
        return;
      }
      const result = await createDirectoryExportJob(
        datasetId,
        preview.plan_id,
        preview.plan_hash
      );
      setJob(result.job);
      window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  const jobActive = job?.status === "queued" || job?.status === "running";
  const jobFailed = job?.status === "failed" || job?.status === "cancelled" || job?.status === "interrupted";
  const progress = job?.progress_total && job.progress_total > 0
    ? Math.min(100, Math.round((job.progress_current / job.progress_total) * 100))
    : 0;
  const outputPath = job?.result && typeof job.result.output_path === "string"
    ? job.result.output_path
    : null;

  return (
    <Modal open={open} title="导出分拣目录 / ZIP" onClose={onClose}>
      <div className="max-h-[84vh] space-y-5 overflow-y-auto px-5 py-5">
        <section className="space-y-3" aria-labelledby="directory-export-options">
          <div>
            <h3 id="directory-export-options" className="text-sm font-semibold text-ink">1. 选择范围和交付方式</h3>
            <p className="mt-1 text-xs leading-5 text-gray-500">目录层级来自“快速分拣 → 分拣层级”，此处只决定导出范围和交付位置。</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className={`cursor-pointer rounded-xl border p-3 ${delivery === "zip" ? "border-gray-900 bg-gray-50" : "border-line"}`}>
              <input type="radio" name="directory-export-delivery" checked={delivery === "zip"} onChange={() => setDelivery("zip")} />
              <span className="ml-2 text-sm font-semibold">ZIP 下载</span>
              <span className="mt-1 block pl-6 text-xs text-gray-500">适合从团队服务器带回本机</span>
            </label>
            <label className={`cursor-pointer rounded-xl border p-3 ${delivery === "directory" ? "border-gray-900 bg-gray-50" : "border-line"}`}>
              <input type="radio" name="directory-export-delivery" checked={delivery === "directory"} onChange={() => setDelivery("directory")} />
              <span className="ml-2 text-sm font-semibold">服务器目录</span>
              <span className="mt-1 block pl-6 text-xs text-gray-500">写入应用托管导出区，不覆盖已有目录</span>
            </label>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="directory-export-scope" className="text-sm font-medium text-gray-700">样本范围</label>
              <select id="directory-export-scope" value={scope} onChange={(event) => setScope(event.target.value as ExportScope)} className="mt-1 min-h-10 w-full rounded-lg border border-line bg-white px-3 text-sm">
                <option value="filtered">当前筛选结果</option>
                <option value="all">全数据集图片</option>
                <option value="split">指定 split</option>
                <option value="selected">已选样本（{selectedSampleIds.length}）</option>
              </select>
            </div>
            {scope === "split" ? (
              <div>
                <label htmlFor="directory-export-split" className="text-sm font-medium text-gray-700">Split</label>
                <select id="directory-export-split" value={selectedSplit} onChange={(event) => setSelectedSplit(event.target.value)} className="mt-1 min-h-10 w-full rounded-lg border border-line bg-white px-3 text-sm">
                  <option value="train">train</option><option value="val">val</option><option value="test">test</option><option value="unassigned">未划分</option>
                </select>
              </div>
            ) : (
              <div>
                <label htmlFor="directory-export-name" className="text-sm font-medium text-gray-700">导出名称（可选）</label>
                <input id="directory-export-name" value={runName} onChange={(event) => setRunName(event.target.value)} maxLength={80} placeholder="例如：客户A首轮" className="mt-1 min-h-10 w-full rounded-lg border border-line px-3 text-sm" />
              </div>
            )}
          </div>
          {scope === "split" && (
            <div>
              <label htmlFor="directory-export-name-split" className="text-sm font-medium text-gray-700">导出名称（可选）</label>
              <input id="directory-export-name-split" value={runName} onChange={(event) => setRunName(event.target.value)} maxLength={80} placeholder="例如：客户A首轮" className="mt-1 min-h-10 w-full rounded-lg border border-line px-3 text-sm" />
            </div>
          )}
          <div className="grid gap-2 sm:grid-cols-3">
            {[
              [includePending, setIncludePending, "包含待定", "进入 pending/"],
              [includeUntriaged, setIncludeUntriaged, "包含未分拣", "进入 untriaged/"],
              [includeOutdated, setIncludeOutdated, "允许过期判定", "按当前层级映射"]
            ].map(([checked, setter, label, hint]) => (
              <label key={String(label)} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line px-3 py-2 text-sm">
                <input type="checkbox" checked={checked as boolean} onChange={(event) => (setter as (value: boolean) => void)(event.target.checked)} className="mt-0.5" />
                <span><span className="block font-medium">{String(label)}</span><span className="block text-xs text-gray-500">{String(hint)}</span></span>
              </label>
            ))}
          </div>
        </section>

        <section className="space-y-3" aria-labelledby="directory-export-preview">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 id="directory-export-preview" className="text-sm font-semibold text-ink">2. 预检目录与容量</h3>
              <p className="mt-1 text-xs text-gray-500">预检冻结一小时；提交前数据变化会要求重新检查。</p>
            </div>
            <button type="button" onClick={() => void runPreview()} disabled={checking || (scope === "selected" && selectedSampleIds.length === 0)} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium hover:bg-gray-50 disabled:opacity-40">
              {checking ? <LoaderCircle size={16} className="animate-spin" /> : <SearchCheck size={16} />} {checking ? "检查中" : "运行预检"}
            </button>
          </div>

          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
          {preview && (
            <div className="space-y-3">
              <div className={`rounded-xl border p-4 ${preview.blocked ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50"}`}>
                <div className="flex items-start gap-2">
                  {preview.blocked ? <AlertTriangle size={18} className="text-red-700" /> : <CheckCircle2 size={18} className="text-emerald-700" />}
                  <div>
                    <div className="text-sm font-semibold">{preview.blocked ? "没有可导出的图片" : `可导出 ${preview.included_count} 张图片`}</div>
                    <div className="mt-1 text-xs text-gray-600">选中 {preview.selected_count} · 排除 {preview.excluded_count} · 图片容量 {formatBytes(preview.total_bytes)}</div>
                    <div className="mt-1 break-all text-xs text-gray-600">输出：{preview.output_name}</div>
                  </div>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-line bg-gray-950 p-3 text-gray-100">
                  <div className="text-xs font-semibold text-gray-400">目录结构</div>
                  <div className="mt-2 max-h-40 space-y-1 overflow-auto font-mono text-xs">
                    {Object.entries(preview.directory_counts).map(([bucket, count]) => <div key={bucket} className="flex justify-between gap-3"><span>{bucket}/</span><span>{count} 张</span></div>)}
                  </div>
                </div>
                <div className="rounded-xl border border-line p-3">
                  <div className="text-xs font-semibold text-gray-700">排除原因</div>
                  <div className="mt-2 space-y-1 text-xs text-gray-600">
                    {Object.keys(preview.exclusion_counts).length === 0 && <div>无排除项</div>}
                    {Object.entries(preview.exclusion_counts).map(([reason, count]) => <div key={reason} className="flex justify-between gap-3"><span>{EXCLUSION_LABELS[reason] ?? reason}</span><span>{count}</span></div>)}
                  </div>
                </div>
              </div>

              {preview.warnings.map((warning) => <div key={warning} className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"><AlertTriangle size={15} className="shrink-0" />{warning}</div>)}

              <div className="overflow-hidden rounded-xl border border-line">
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] bg-gray-50 px-3 py-2 text-xs font-medium text-gray-600"><span>源文件</span><span>导出位置 / 排除原因</span></div>
                <div className="max-h-48 divide-y divide-line overflow-auto">
                  {preview.items.map((item) => (
                    <div key={item.sample_id} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-3 px-3 py-2 text-xs">
                      <span className="truncate" title={item.source_relative_path}>{item.source_relative_path}</span>
                      <span className={item.included ? "truncate font-mono text-gray-700" : "text-amber-700"} title={item.target_relative_path ?? undefined}>{item.target_relative_path ?? EXCLUSION_LABELS[item.exclusion_reason ?? ""] ?? item.exclusion_reason}</span>
                    </div>
                  ))}
                </div>
                {preview.page_count > 1 && (
                  <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-gray-600">
                    <button type="button" disabled={preview.page <= 1 || paging} onClick={() => void changePage(preview.page - 1)} className="inline-flex items-center gap-1 disabled:opacity-30"><ChevronLeft size={15} /> 上一页</button>
                    <span>{preview.page} / {preview.page_count}</span>
                    <button type="button" disabled={preview.page >= preview.page_count || paging} onClick={() => void changePage(preview.page + 1)} className="inline-flex items-center gap-1 disabled:opacity-30">下一页 <ChevronRight size={15} /></button>
                  </div>
                )}
              </div>
            </div>
          )}
        </section>

        {job && (
          <section aria-live="polite" className={`rounded-xl border p-4 ${job.status === "succeeded" ? "border-emerald-200 bg-emerald-50" : jobFailed ? "border-red-200 bg-red-50" : "border-blue-200 bg-blue-50"}`}>
            <div className="flex items-center gap-2 text-sm font-semibold">
              {delivery === "zip" ? <Archive size={17} /> : <FolderOpen size={17} />}
              {job.status === "succeeded" ? "导出完成" : jobFailed ? "导出未完成" : "后台任务正在执行"}
            </div>
            <div className="mt-1 text-xs text-gray-600">{STAGE_LABELS[job.stage] ?? job.stage}{jobActive ? ` · ${progress}%` : ""}</div>
            {job.error && typeof job.error.message === "string" && <div className="mt-2 text-xs text-red-700">{job.error.message}</div>}
            {outputPath && <div className="mt-2 break-all rounded-lg bg-white/70 px-3 py-2 font-mono text-xs text-gray-700">服务器目录：{outputPath}</div>}
          </section>
        )}

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <button type="button" onClick={onClose} className="min-h-10 rounded-lg border border-line px-4 text-sm font-medium">关闭</button>
          <button type="button" onClick={() => void submitOrDownload()} disabled={!preview || preview.blocked || checking || submitting || jobActive || (job?.status === "succeeded" && delivery === "directory")} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white disabled:bg-gray-300">
            {submitting ? <LoaderCircle size={17} className="animate-spin" /> : delivery === "zip" && job?.status === "succeeded" ? <Download size={17} /> : delivery === "zip" ? <Archive size={17} /> : <FolderOpen size={17} />}
            {submitting ? "处理中" : delivery === "zip" && job?.status === "succeeded" ? "下载 ZIP" : jobFailed ? "重新提交" : delivery === "zip" ? "生成 ZIP" : job?.status === "succeeded" ? "已写入服务器" : "写入服务器目录"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
