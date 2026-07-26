import axios from "axios";
import { Activity, Ban, RefreshCw, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { cancelJob, listJobs, retryJob } from "../api/client";
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
      await (action === "cancel" ? cancelJob(job.id) : retryJob(job.id));
      await load(true);
    } catch {
      setError(action === "cancel" ? "取消请求未能提交" : "重试未能创建");
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
                          <span>{job.stage}</span>
                          {progress !== null ? <span>{progress}%</span> : null}
                        </div>
                        {progress !== null ? (
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100">
                            <div className="h-full rounded-full bg-blue-600 transition-[width]" style={{ width: `${progress}%` }} />
                          </div>
                        ) : null}
                        {errorMessage(job) ? <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{errorMessage(job)}</p> : null}
                        {canCancel || canRetry ? (
                          <div className="mt-3 flex justify-end gap-2">
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
