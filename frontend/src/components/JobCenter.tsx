import axios from "axios";
import { Activity, Ban, Download, RefreshCw, RotateCcw, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { cancelJob, createLabelmeImportRollbackJob, createMetadataImportRollbackJob, downloadJobArtifact, listJobs, retryJob } from "../api/client";
import type { Job, JobStatus } from "../types/job";

const statusCopy: Record<JobStatus, string> = {
  queued: "等待中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断"
};

const terminalRetryStatuses = new Set<JobStatus>(["failed", "cancelled", "interrupted"]);
const stageCopy: Record<string, string> = {
  queued: "等待开始",
  starting: "正在启动",
  enumerating: "枚举文件",
  hashing: "校验变化文件",
  writing: "写入元数据",
  missing_detection: "检查缺失文件",
  prechecking: "任务预检",
  writing_metadata: "分批写入元数据",
  rolling_back_metadata: "恢复导入前元数据",
  parsing_labelme: "解析 LabelMe 标注",
  writing_annotations: "分批写入标注",
  rolling_back_annotations: "恢复导入前标注",
  writing_archive: "写入导出包",
  writing_json: "写入 COCO JSON",
  generating_thumbnails: "生成图片缩略图",
  scanning_thumbnail_cache: "盘点缩略图缓存",
  pruning_thumbnail_cache: "清理缩略图缓存",
  preparing_backup: "准备元数据备份",
  copying_database: "复制 SQLite 快照",
  verifying_backup: "检查备份完整性",
  hashing_backup: "计算备份校验值",
  finalizing: "校验导出产物",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  process_stopped: "进程已停止"
};

function statusTone(status: JobStatus): string {
  if (status === "running") return "bg-blue-50 text-blue-700";
  if (status === "queued") return "bg-amber-50 text-amber-700";
  if (status === "succeeded") return "bg-emerald-50 text-emerald-700";
  if (status === "failed") return "bg-red-50 text-red-700";
  return "bg-gray-100 text-gray-600";
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function errorMessage(job: Job): string | null {
  const message = job.error?.message;
  return typeof message === "string" ? message : null;
}

function scanResultSummary(job: Job): string | null {
  if (job.job_type !== "dataset.scan" || !job.result) return null;
  const imported = job.result.imported;
  const updated = job.result.updated;
  const unchanged = job.result.unchanged;
  if (
    typeof imported !== "number"
    || typeof updated !== "number"
    || typeof unchanged !== "number"
  ) {
    return null;
  }
  return `新增 ${imported} · 变更 ${updated} · 未变 ${unchanged}`;
}

function annotationExportSummary(job: Job): string | null {
  if (job.job_type !== "annotation.export" || !job.result) return null;
  const format = job.result.format;
  const sampleCount = job.result.exported_sample_count;
  const artifact = job.result.artifact;
  if (
    typeof format !== "string"
    || typeof sampleCount !== "number"
    || !artifact
    || typeof artifact !== "object"
  ) {
    return null;
  }
  const size = (artifact as Record<string, unknown>).size_bytes;
  const formatCopy: Record<string, string> = {
    labelme: "LabelMe",
    coco_detection: "COCO detection",
    coco_segmentation: "COCO segmentation",
    yolo_detection: "YOLO detection",
    yolo_segmentation: "YOLO segmentation",
    voc: "Pascal VOC"
  };
  return `${formatCopy[format] ?? format} · ${sampleCount} 个样本${typeof size === "number" ? ` · ${Math.ceil(size / 1024)} KiB` : ""}`;
}

function thumbnailSummary(job: Job): string | null {
  if (job.job_type !== "thumbnail.generate" || !job.result) return null;
  const generated = job.result.generated_count;
  const cached = job.result.cached_count;
  const failed = job.result.failed_count;
  if (
    typeof generated !== "number"
    || typeof cached !== "number"
    || typeof failed !== "number"
  ) {
    return null;
  }
  return `缩略图：生成 ${generated} · 复用 ${cached} · 失败 ${failed}`;
}

function thumbnailMaintenanceSummary(job: Job): string | null {
  if (job.job_type !== "thumbnail.maintain" || !job.result) return null;
  const oldSpec = job.result.old_spec_removed_count;
  const orphan = job.result.orphan_removed_count;
  const capacity = job.result.capacity_removed_count;
  const sizeAfter = job.result.size_after_bytes;
  if (
    typeof oldSpec !== "number"
    || typeof orphan !== "number"
    || typeof capacity !== "number"
    || typeof sizeAfter !== "number"
  ) {
    return null;
  }
  return `缓存清理：旧规格 ${oldSpec} · 孤立 ${orphan} · 容量淘汰 ${capacity} · 剩余 ${(sizeAfter / 1024 / 1024).toFixed(1)} MiB`;
}

function metadataImportSummary(job: Job): string | null {
  if (job.job_type !== "metadata.import" || !job.result) return null;
  const updated = job.result.updated;
  const unique = job.result.unique_samples_changed;
  const batches = job.result.batches_committed;
  if (typeof updated !== "number" || typeof unique !== "number" || typeof batches !== "number") {
    return null;
  }
  return `元数据：写入 ${updated} 行 · 影响 ${unique} 个样本 · ${batches} 批`;
}

function metadataRollbackSummary(job: Job): string | null {
  if (job.job_type !== "metadata.import.rollback" || !job.result) return null;
  const restored = job.result.restored;
  const missing = job.result.missing;
  if (typeof restored !== "number" || typeof missing !== "number") return null;
  return `元数据回滚：恢复 ${restored} 个样本${missing > 0 ? ` · 缺失 ${missing}` : ""}`;
}

function labelmeImportSummary(job: Job): string | null {
  if (job.job_type !== "annotation.import.labelme" || !job.result) return null;
  const imported = job.result.imported_samples;
  const annotations = job.result.planned_annotations;
  const batches = job.result.batches_committed;
  if (typeof imported !== "number" || typeof annotations !== "number" || typeof batches !== "number") return null;
  return `LabelMe：写入 ${imported} 个样本 · ${annotations} 个对象 · ${batches} 批`;
}

function labelmeRollbackSummary(job: Job): string | null {
  if (job.job_type !== "annotation.import.labelme.rollback" || !job.result) return null;
  const restored = job.result.restored;
  const missing = job.result.missing;
  if (typeof restored !== "number" || typeof missing !== "number") return null;
  return `LabelMe 回滚：恢复 ${restored} 个样本${missing > 0 ? ` · 缺失 ${missing}` : ""}`;
}

function databaseBackupSummary(job: Job): string | null {
  if (job.job_type !== "database.backup" || !job.result) return null;
  const artifact = job.result.artifact;
  const verification = job.result.verification;
  if (!artifact || typeof artifact !== "object" || !verification || typeof verification !== "object") {
    return null;
  }
  const size = (artifact as Record<string, unknown>).size_bytes;
  const quickCheck = (verification as Record<string, unknown>).quick_check;
  const revision = (verification as Record<string, unknown>).current_revision;
  if (typeof size !== "number" || typeof quickCheck !== "string") return null;
  return `SQLite 元数据 ${(size / 1024 / 1024).toFixed(1)} MiB · 完整性 ${quickCheck}${typeof revision === "string" ? ` · ${revision}` : ""}`;
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

export default function JobCenter() {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [schemaUnavailable, setSchemaUnavailable] = useState(false);
  const [error, setError] = useState("");
  const [actingId, setActingId] = useState<number | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const response = await listJobs();
      setJobs(response.items);
      setSchemaUnavailable(false);
      setError("");
    } catch (caught) {
      if (axios.isAxiosError(caught) && caught.response?.status === 409) {
        setSchemaUnavailable(true);
        setJobs([]);
        setError("");
      } else {
        setError("暂时无法读取任务状态");
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const refresh = () => void load(true);
    window.addEventListener("dataset-manager:jobs-changed", refresh);
    return () => window.removeEventListener("dataset-manager:jobs-changed", refresh);
  }, [load]);

  useEffect(() => {
    if (schemaUnavailable) return;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [load, schemaUnavailable]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const activeCount = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "running").length,
    [jobs]
  );
  const failedCount = useMemo(
    () => jobs.filter((job) => job.status === "failed" || job.status === "interrupted").length,
    [jobs]
  );

  const buttonLabel = schemaUnavailable
    ? "任务中心待启用"
    : activeCount > 0
      ? `${activeCount} 个任务进行中`
      : failedCount > 0
        ? `${failedCount} 个任务需查看`
        : "任务";

  async function act(job: Job, action: "cancel" | "retry") {
    setActingId(job.id);
    try {
      const updatedJob = await (action === "cancel" ? cancelJob(job.id) : retryJob(job.id));
      await load(true);
      window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
      window.dispatchEvent(new CustomEvent("dataset-manager:job-action", {
        detail: { job: updatedJob }
      }));
    } catch {
      setError(action === "cancel" ? "取消请求未能提交" : "重试未能创建");
    } finally {
      setActingId(null);
    }
  }

  async function downloadArtifact(job: Job) {
    setActingId(job.id);
    try {
      const result = await downloadJobArtifact(job.id);
      triggerDownload(result.blob, result.filename);
    } catch {
      setError("任务产物已不可用，请重新提交任务");
    } finally {
      setActingId(null);
    }
  }

  async function rollbackImport(job: Job) {
    setActingId(job.id);
    try {
      if (job.job_type === "metadata.import") {
        await createMetadataImportRollbackJob(job.id);
      } else {
        await createLabelmeImportRollbackJob(job.id);
      }
      await load(true);
      window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
    } catch (caught) {
      setError(apiDetail(caught) ?? "回滚任务未能创建");
    } finally {
      setActingId(null);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="fixed bottom-4 right-4 z-30 inline-flex min-h-11 items-center gap-2 rounded-full border border-line bg-white px-4 py-2 text-sm font-medium text-ink shadow-lg shadow-gray-200/70 transition hover:border-gray-300 hover:bg-gray-50"
      >
        <Activity size={17} className={activeCount > 0 ? "text-blue-600" : failedCount > 0 ? "text-red-600" : "text-muted"} />
        <span>{buttonLabel}</span>
      </button>

      {open ? (
        <div className="fixed inset-0 z-50">
          <button
            type="button"
            aria-label="关闭任务抽屉"
            className="absolute inset-0 bg-gray-950/20"
            onClick={() => setOpen(false)}
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="job-center-title"
            className="absolute inset-y-0 right-0 flex w-full max-w-[430px] flex-col border-l border-line bg-white shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <div>
                <h2 id="job-center-title" className="text-base font-semibold text-ink">本地任务</h2>
                <p className="mt-0.5 text-xs text-muted">长任务会在这里显示阶段、进度与结果</p>
              </div>
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => void load()} aria-label="刷新任务" className="rounded-lg p-2 text-muted hover:bg-gray-100 hover:text-ink">
                  <RefreshCw size={17} className={loading ? "animate-spin" : ""} />
                </button>
                <button type="button" onClick={() => setOpen(false)} aria-label="关闭" className="rounded-lg p-2 text-muted hover:bg-gray-100 hover:text-ink">
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {schemaUnavailable ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                  <p className="text-sm font-medium text-amber-900">完成数据库升级后启用</p>
                  <p className="mt-1 text-sm leading-6 text-amber-800">当前数据库仍保持旧结构。请先停止后端并按“数据库维护”说明完成离线升级；这里不会自动改表。</p>
                </div>
              ) : error ? (
                <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
              ) : loading && jobs.length === 0 ? (
                <div className="py-16 text-center text-sm text-muted">正在读取任务…</div>
              ) : jobs.length === 0 ? (
                <div className="py-16 text-center">
                  <Activity size={28} className="mx-auto text-gray-300" />
                  <p className="mt-3 text-sm font-medium text-ink">还没有本地任务</p>
                  <p className="mt-1 text-xs text-muted">后续扫描和导出任务会逐批接入</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {jobs.map((job) => {
                    const progress = job.progress_total && job.progress_total > 0
                      ? Math.min(100, Math.round((job.progress_current / job.progress_total) * 100))
                      : null;
                    const canCancel = job.status === "queued" || job.status === "running";
                    const canRetry = terminalRetryStatuses.has(job.status);
                    const canDownload = (job.job_type === "annotation.export" || job.job_type === "database.backup") && job.status === "succeeded";
                    const canRollback = (job.job_type === "metadata.import" || job.job_type === "annotation.import.labelme")
                      && (job.result?.rollback_available === true || job.status === "interrupted");
                    return (
                      <article key={job.id} className="rounded-2xl border border-line p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <h3 className="truncate text-sm font-semibold text-ink">{job.title}</h3>
                            <p className="mt-1 truncate text-xs text-muted">{job.job_type} · {formatTime(job.created_at)}</p>
                          </div>
                          <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-medium ${statusTone(job.status)}`}>{statusCopy[job.status]}</span>
                        </div>
                        <div className="mt-3 flex items-center justify-between text-xs text-muted">
                          <span>{stageCopy[job.stage] ?? job.stage}</span>
                          {progress !== null ? <span>{progress}%</span> : null}
                        </div>
                        {progress !== null ? (
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100">
                            <div className="h-full rounded-full bg-blue-600 transition-[width]" style={{ width: `${progress}%` }} />
                          </div>
                        ) : null}
                        {errorMessage(job) ? <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{errorMessage(job)}</p> : null}
                        {scanResultSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{scanResultSummary(job)}</p> : null}
                        {annotationExportSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{annotationExportSummary(job)}</p> : null}
                        {thumbnailSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{thumbnailSummary(job)}</p> : null}
                        {thumbnailMaintenanceSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{thumbnailMaintenanceSummary(job)}</p> : null}
                        {metadataImportSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{metadataImportSummary(job)}</p> : null}
                        {metadataRollbackSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{metadataRollbackSummary(job)}</p> : null}
                        {labelmeImportSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{labelmeImportSummary(job)}</p> : null}
                        {labelmeRollbackSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{labelmeRollbackSummary(job)}</p> : null}
                        {databaseBackupSummary(job) ? <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{databaseBackupSummary(job)}</p> : null}
                        {canCancel || canRetry || canDownload || canRollback ? (
                          <div className="mt-3 flex justify-end gap-2">
                            {canRollback ? (
                              <button type="button" disabled={actingId === job.id} onClick={() => void rollbackImport(job)} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-gray-50 disabled:opacity-50">
                                <Undo2 size={14} /> 回滚
                              </button>
                            ) : null}
                            {canDownload ? (
                              <button type="button" disabled={actingId === job.id} onClick={() => void downloadArtifact(job)} className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50">
                                <Download size={14} /> 下载
                              </button>
                            ) : null}
                            {canCancel ? (
                              <button type="button" disabled={actingId === job.id} onClick={() => void act(job, "cancel")} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-gray-50 disabled:opacity-50">
                                <Ban size={14} /> 取消
                              </button>
                            ) : null}
                            {canRetry ? (
                              <button type="button" disabled={actingId === job.id} onClick={() => void act(job, "retry")} className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50">
                                <RotateCcw size={14} /> 重试
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              )}
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}

function apiDetail(caught: unknown): string | null {
  if (!axios.isAxiosError(caught)) return null;
  const detail = caught.response?.data?.detail;
  return typeof detail === "string" ? detail : null;
}
