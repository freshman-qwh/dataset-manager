import { AlertTriangle, ChevronLeft, ChevronRight, Copy, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getDuplicateReport } from "../api/client";
import type { DuplicateReport } from "../types/dataset";
import Modal from "./Modal";

interface DatasetIssueModalProps {
  datasetId: number;
  issue: "missing" | "duplicate" | null;
  missingCount: number;
  permissionDeniedCount: number;
  duplicateGroupCount: number;
  duplicateSampleCount: number;
  duplicateReport: DuplicateReport | null;
  onClose: () => void;
  onFilterMissing: () => void;
  onFilterPermissionDenied: () => void;
  onFilterDuplicates: () => void;
  onFilterDuplicateHash: (fileHash: string) => void;
  onRepairMissing: () => void;
}

const splitLabels: Record<string, string> = {
  train: "训练集",
  val: "验证集",
  test: "测试集",
  unassigned: "未分配"
};

const statusLabels: Record<string, string> = {
  normal: "文件正常",
  missing: "文件缺失",
  permission_denied: "无读取权限",
  not_reviewed: "未审核",
  in_review: "审核中",
  approved: "已通过",
  rejected: "已拒绝",
  not_started: "未开始标注",
  in_progress: "标注中",
  completed_empty: "已确认无目标",
  completed_with_objects: "已完成标注"
};

function splitLabel(split: string | null): string {
  const normalized = split || "unassigned";
  return splitLabels[normalized] ?? normalized;
}

function statusLabel(status: string): string {
  return statusLabels[status] ?? status;
}

export default function DatasetIssueModal({
  datasetId,
  issue,
  missingCount,
  permissionDeniedCount,
  duplicateGroupCount,
  duplicateSampleCount,
  duplicateReport,
  onClose,
  onFilterMissing,
  onFilterPermissionDenied,
  onFilterDuplicates,
  onFilterDuplicateHash,
  onRepairMissing
}: DatasetIssueModalProps) {
  const [report, setReport] = useState<DuplicateReport | null>(duplicateReport);
  const [leakageOnly, setLeakageOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (issue !== "duplicate") {
      return;
    }
    setLeakageOnly(false);
    setPage(1);
    setReport(duplicateReport);
  }, [duplicateReport, issue]);

  useEffect(() => {
    if (issue !== "duplicate") {
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void getDuplicateReport(datasetId, {
      leakageOnly,
      page,
      pageSize: 12,
      signal: controller.signal
    })
      .then((nextReport) => {
        setReport(nextReport);
        if (nextReport.page !== page) {
          setPage(nextReport.page);
        }
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setError(requestError instanceof Error ? requestError.message : "重复报告加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [datasetId, issue, leakageOnly, page]);

  const pageCount = useMemo(() => {
    if (!report) return 1;
    const filteredCount = report.filtered_group_count ?? report.group_count;
    const pageSize = report.page_size ?? 12;
    return Math.max(Math.ceil(filteredCount / pageSize), 1);
  }, [report]);

  if (!issue) {
    return null;
  }

  if (issue === "missing") {
    return (
      <Modal open title="缺失文件" onClose={onClose}>
        <div className="space-y-4 px-5 py-5">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle size={17} />
              文件可用性异常
            </div>
            <div className="mt-2">缺失 {missingCount} 个，无权限 {permissionDeniedCount} 个。</div>
          </div>
          <div className="flex flex-wrap gap-2">
            {missingCount > 0 && (
              <button type="button" onClick={onFilterMissing} className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                查看缺失
              </button>
            )}
            {permissionDeniedCount > 0 && (
              <button type="button" onClick={onFilterPermissionDenied} className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                查看无权限
              </button>
            )}
            {(missingCount > 0 || permissionDeniedCount > 0) && (
              <button type="button" onClick={onRepairMissing} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
                修复缺失
              </button>
            )}
          </div>
        </div>
      </Modal>
    );
  }

  const visibleReport = report ?? duplicateReport;
  const crossSplitGroupCount = visibleReport?.cross_split_group_count ?? 0;
  const crossSplitSampleCount = visibleReport?.cross_split_sample_count ?? 0;

  return (
    <Modal open title="精确重复与划分泄漏" onClose={onClose} size="lg">
      <div className="max-h-[calc(100vh-7rem)] space-y-4 overflow-y-auto px-5 py-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <div className="flex items-center gap-2 font-medium">
              <Copy size={17} />
              {visibleReport?.group_count ?? duplicateGroupCount} 组精确重复
            </div>
            <div className="mt-1 text-xs text-amber-700">
              涉及 {visibleReport?.duplicate_sample_count ?? duplicateSampleCount} 个样本，仅比较本地 SHA-256。
            </div>
          </div>
          <div className={`rounded-lg border p-3 text-sm ${crossSplitGroupCount > 0 ? "border-red-200 bg-red-50 text-red-900" : "border-emerald-200 bg-emerald-50 text-emerald-900"}`}>
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle size={17} />
              {crossSplitGroupCount} 组跨训练划分泄漏
            </div>
            <div className="mt-1 text-xs opacity-75">涉及 {crossSplitSampleCount} 个样本；未分配样本本身不计为泄漏。</div>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={leakageOnly}
              onChange={(event) => {
                setLeakageOnly(event.target.checked);
                setPage(1);
              }}
              className="h-4 w-4 rounded border-gray-300 text-blue-600"
            />
            仅显示跨 train / val / test 的重复组
          </label>
          {loading && <LoaderCircle aria-label="正在加载重复报告" className="animate-spin text-gray-400" size={18} />}
        </div>

        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        {visibleReport && visibleReport.groups.length > 0 ? (
          <div className="max-h-[52vh] space-y-3 overflow-auto pr-1">
            {visibleReport.groups.map((group) => (
              <section key={group.file_hash} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-medium text-gray-800" title={group.file_hash}>
                        {group.file_hash.slice(0, 16)}…
                      </span>
                      {group.cross_split && (
                        <span className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-medium text-red-700">跨划分泄漏</span>
                      )}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {Object.entries(group.split_counts ?? {}).map(([splitName, count]) => (
                        <span key={splitName} className="rounded-full bg-gray-100 px-2 py-1 text-[11px] text-gray-600">
                          {splitLabel(splitName)} {count}
                        </span>
                      ))}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => onFilterDuplicateHash(group.file_hash)}
                    className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  >
                    在样本区查看此组
                  </button>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {group.samples.map((sample) => (
                    <div key={sample.id} className="min-w-0 rounded-lg bg-gray-50 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium text-ink" title={sample.filename}>{sample.filename}</span>
                        <span className="shrink-0 text-gray-500">{splitLabel(sample.split)}</span>
                      </div>
                      <div className="mt-1 truncate text-gray-500" title={sample.relative_path}>{sample.relative_path}</div>
                      <div className="mt-1 text-gray-400">
                        {statusLabel(sample.file_status)} · {statusLabel(sample.review_status)} · {statusLabel(sample.annotation_progress)}
                      </div>
                    </div>
                  ))}
                </div>
                {group.samples_truncated && (
                  <div className="mt-2 text-xs text-gray-500">
                    当前仅展示前 {group.samples.length} 个样本；使用“在样本区查看此组”浏览完整结果。
                  </div>
                )}
              </section>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-gray-500">
            {leakageOnly ? "当前没有跨训练划分的精确重复。" : "当前没有精确重复样本。"}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <button type="button" onClick={onFilterDuplicates} disabled={duplicateSampleCount === 0} className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50">
            查看全部重复样本
          </button>
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <button type="button" title="上一页" aria-label="上一页" disabled={!visibleReport?.has_previous || loading} onClick={() => setPage((current) => Math.max(current - 1, 1))} className="rounded-lg border border-line p-2 hover:bg-gray-50 disabled:opacity-40">
              <ChevronLeft size={16} />
            </button>
            <span>第 {visibleReport?.page ?? page} / {pageCount} 页</span>
            <button type="button" title="下一页" aria-label="下一页" disabled={!visibleReport?.has_next || loading} onClick={() => setPage((current) => current + 1)} className="rounded-lg border border-line p-2 hover:bg-gray-50 disabled:opacity-40">
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
