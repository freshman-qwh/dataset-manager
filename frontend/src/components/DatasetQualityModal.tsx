import { AlertCircle, AlertTriangle, ExternalLink, Filter, Info, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { DatasetQualityReport, QualityIssue, QualityIssueSeverity } from "../types/dataset";
import Modal from "./Modal";

interface DatasetQualityModalProps {
  open: boolean;
  report: DatasetQualityReport | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onFilterEmpty: () => void;
  onFilterReview: (status: string) => void;
  onOpenIssue: (issue: QualityIssue) => void;
}

const severityCopy: Record<QualityIssueSeverity, string> = {
  error: "错误",
  warning: "警告",
  info: "提示"
};

const severityClasses: Record<QualityIssueSeverity, string> = {
  error: "border-red-200 bg-red-50 text-red-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  info: "border-blue-200 bg-blue-50 text-blue-800"
};

function severityIcon(severity: QualityIssueSeverity) {
  if (severity === "error") return <AlertCircle size={17} />;
  if (severity === "warning") return <AlertTriangle size={17} />;
  return <Info size={17} />;
}

export default function DatasetQualityModal({
  open,
  report,
  loading,
  error,
  onClose,
  onRefresh,
  onFilterEmpty,
  onFilterReview,
  onOpenIssue
}: DatasetQualityModalProps) {
  const [severity, setSeverity] = useState<QualityIssueSeverity | "all">("all");
  const [code, setCode] = useState("all");

  useEffect(() => {
    if (open) {
      setSeverity("all");
      setCode("all");
    }
  }, [open]);

  const issueTypes = useMemo(() => {
    const titles = new Map<string, string>();
    for (const issue of report?.issues ?? []) {
      titles.set(issue.code, issue.title);
    }
    return Array.from(titles.entries()).sort(([left], [right]) => left.localeCompare(right));
  }, [report]);
  const visibleIssues = useMemo(
    () =>
      (report?.issues ?? []).filter(
        (issue) => (severity === "all" || issue.severity === severity) && (code === "all" || issue.code === code)
      ),
    [code, report, severity]
  );
  const emptyCount = report?.check_counts.EMPTY_ANNOTATIONS ?? 0;

  return (
    <Modal open={open} title="数据健康工作台" onClose={onClose} size="xl">
      <div className="flex max-h-[82vh] min-h-[32rem] flex-col">
        <div className="border-b border-line px-5 py-4">
          <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
            <div>
              <p className="text-sm text-gray-600">检查标注几何、重复对象、split 泄漏、类别分布和审查状态。</p>
              {report && <p className="mt-1 text-xs text-gray-400">最近复检：{new Date(report.generated_at).toLocaleString()}</p>}
            </div>
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-blue-300"
            >
              {loading ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
              重新检查
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
          {loading && !report && (
            <div className="flex h-64 items-center justify-center gap-2 text-sm text-gray-500">
              <Loader2 className="animate-spin" size={18} />
              正在检查数据集
            </div>
          )}
          {report && (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <div className="rounded-lg border border-line bg-gray-50 p-3">
                  <div className="text-xs text-gray-500">图片 / 已标注</div>
                  <div className="mt-1 text-xl font-semibold text-ink">{report.image_sample_count} / {report.annotated_sample_count}</div>
                </div>
                <button type="button" onClick={() => setSeverity("error")} className="rounded-lg border border-red-200 bg-red-50 p-3 text-left text-red-800">
                  <div className="text-xs">错误</div><div className="mt-1 text-xl font-semibold">{report.error_count}</div>
                </button>
                <button type="button" onClick={() => setSeverity("warning")} className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-left text-amber-800">
                  <div className="text-xs">警告</div><div className="mt-1 text-xl font-semibold">{report.warning_count}</div>
                </button>
                <button type="button" onClick={() => setSeverity("info")} className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-left text-blue-800">
                  <div className="text-xs">提示</div><div className="mt-1 text-xl font-semibold">{report.info_count}</div>
                </button>
                <button type="button" onClick={onFilterEmpty} disabled={emptyCount === 0} className="rounded-lg border border-line bg-white p-3 text-left disabled:cursor-not-allowed disabled:opacity-50">
                  <div className="text-xs text-gray-500">空标注图片</div><div className="mt-1 text-xl font-semibold text-ink">{emptyCount}</div>
                </button>
              </div>

              <div className="grid gap-3 rounded-lg border border-line bg-white p-3 text-sm sm:grid-cols-4">
                {[
                  ["unlabeled", "未标注"],
                  ["in_review", "待审核"],
                  ["approved", "已通过"],
                  ["rejected", "已拒绝"]
                ].map(([status, label]) => (
                  <button key={status} type="button" onClick={() => onFilterReview(status)} className="rounded-md px-3 py-2 text-left hover:bg-gray-50">
                    <span className="text-gray-500">{label}</span>
                    <span className="ml-2 font-semibold text-ink">{report.review_status_counts[status] ?? 0}</span>
                  </button>
                ))}
              </div>

              <div className="flex flex-col gap-3 rounded-lg border border-line bg-gray-50 p-3 sm:flex-row sm:items-center">
                <Filter size={17} className="text-gray-500" />
                <select value={severity} onChange={(event) => setSeverity(event.target.value as QualityIssueSeverity | "all")} className="rounded-lg border border-line bg-white px-3 py-2 text-sm">
                  <option value="all">全部严重度</option>
                  <option value="error">错误</option>
                  <option value="warning">警告</option>
                  <option value="info">提示</option>
                </select>
                <select value={code} onChange={(event) => setCode(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-2 text-sm">
                  <option value="all">全部问题类型</option>
                  {issueTypes.map(([issueCode, title]) => <option key={issueCode} value={issueCode}>{title} · {issueCode}（{report.check_counts[issueCode] ?? 0}）</option>)}
                </select>
                <span className="text-xs text-gray-500">显示 {visibleIssues.length} / {report.issue_count}</span>
              </div>

              {visibleIssues.length === 0 ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-8 text-center text-sm text-emerald-700">当前筛选下没有质量问题。</div>
              ) : (
                <div className="space-y-2">
                  {visibleIssues.map((issue, index) => (
                    <div key={`${issue.code}-${issue.sample_id ?? "dataset"}-${issue.annotation_id ?? index}`} className={`rounded-lg border p-3 ${severityClasses[issue.severity]}`}>
                      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm font-semibold">{severityIcon(issue.severity)}{issue.title}<span className="rounded bg-white/60 px-1.5 py-0.5 font-mono text-[10px]">{issue.code}</span></div>
                          <p className="mt-1 text-xs opacity-90">{issue.message}</p>
                          {issue.sample_path && <p className="mt-1 truncate text-xs font-medium" title={issue.sample_path}>{issue.sample_path}</p>}
                        </div>
                        {issue.sample_id && (
                          <button type="button" onClick={() => onOpenIssue(issue)} className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md bg-white px-3 py-2 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50">
                            <ExternalLink size={14} />
                            {issue.annotation_id ? "定位对象" : "打开样本"}
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {report.truncated_issue_count > 0 && <p className="text-xs text-gray-500">另有 {report.truncated_issue_count} 条问题未展开，请先按严重度和类型处理当前结果。</p>}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
