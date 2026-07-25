import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  FileOutput,
  GitBranch,
  Loader2,
  RefreshCw,
  ShieldAlert
} from "lucide-react";

import type { TrainingReadinessReport, TrainingReadinessStatus } from "../types/dataset";
import Modal from "./Modal";

interface TrainingReadinessModalProps {
  open: boolean;
  report: TrainingReadinessReport | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onShowCompleted: () => void;
  onShowEmpty: () => void;
  onShowReview: () => void;
  onShowSplit: (split: string) => void;
  onOpenQuality: () => void;
  onOpenSplitPlan: () => void;
  onOpenExport: () => void;
}

const readinessCopy: Record<TrainingReadinessStatus, {
  label: string;
  detail: string;
  classes: string;
}> = {
  blocked: {
    label: "存在导出阻断",
    detail: "先处理阻断问题，再确认划分和训练格式。",
    classes: "border-red-200 bg-red-50 text-red-800"
  },
  needs_attention: {
    label: "建议先完善",
    detail: "当前可以继续检查，但仍有待处理样本、审核或划分事项。",
    classes: "border-amber-200 bg-amber-50 text-amber-800"
  },
  ready: {
    label: "可以准备导出",
    detail: "主要检查已通过，请确认范围和格式后导出。",
    classes: "border-emerald-200 bg-emerald-50 text-emerald-800"
  }
};

const formatCopy: Record<string, string> = {
  coco_detection: "COCO 检测",
  coco_segmentation: "COCO 分割",
  yolo_detection: "YOLO 检测",
  yolo_segmentation: "YOLO 分割",
  voc: "Pascal VOC",
  labelme: "LabelMe",
  csv: "CSV 标签表",
  manifest: "Manifest 清单"
};

function SummaryButton({
  label,
  value,
  detail,
  onClick,
  tone = "default"
}: {
  label: string;
  value: number;
  detail: string;
  onClick: () => void;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-xl border p-4 text-left transition hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 ${
        tone === "danger" ? "border-red-200 bg-red-50" : "border-line bg-white"
      }`}
    >
      <div className={`text-xs font-medium ${tone === "danger" ? "text-red-700" : "text-gray-500"}`}>{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone === "danger" ? "text-red-800" : "text-ink"}`}>{value}</div>
      <div className={`mt-1 text-xs ${tone === "danger" ? "text-red-600" : "text-gray-500"}`}>{detail}</div>
    </button>
  );
}

export default function TrainingReadinessModal({
  open,
  report,
  loading,
  error,
  onClose,
  onRefresh,
  onShowCompleted,
  onShowEmpty,
  onShowReview,
  onShowSplit,
  onOpenQuality,
  onOpenSplitPlan,
  onOpenExport
}: TrainingReadinessModalProps) {
  const status = report ? readinessCopy[report.status] : null;
  const classificationTask = report?.task_type === "classification";
  const splitOrder = ["train", "val", "test", "unassigned"];

  return (
    <Modal open={open} title="准备训练" onClose={onClose} size="xl">
      <div className="flex max-h-[84vh] min-h-[34rem] flex-col">
        <div className="border-b border-line px-5 py-4">
          <ol className="grid grid-cols-4 gap-2" aria-label="训练准备步骤">
            {[
              ["1", "检查"],
              ["2", "修复"],
              ["3", "确认"],
              ["4", "导出"]
            ].map(([number, label], index) => (
              <li key={number} className="flex min-w-0 items-center gap-2">
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  index === 0 ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-500"
                }`}>{number}</span>
                <span className={`truncate text-xs font-medium ${index === 0 ? "text-ink" : "text-gray-400"}`}>{label}</span>
                {index < 3 && <span className="hidden h-px min-w-3 flex-1 bg-line sm:block" />}
              </li>
            ))}
          </ol>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          {error && (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <span>{error}</span>
              <button type="button" onClick={onRefresh} className="inline-flex min-h-9 shrink-0 items-center gap-2 rounded-lg bg-white px-3 text-xs font-semibold shadow-sm">
                <RefreshCw size={14} />
                重试
              </button>
            </div>
          )}
          {loading && !report && (
            <div className="flex h-72 items-center justify-center gap-2 text-sm text-gray-500">
              <Loader2 size={18} className="animate-spin" />
              正在汇总训练准备状态
            </div>
          )}
          {report && status && (
            <div className="space-y-5">
              <div className={`flex flex-col justify-between gap-3 rounded-xl border px-4 py-4 sm:flex-row sm:items-center ${status.classes}`}>
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {report.status === "ready" ? <CheckCircle2 size={18} /> : report.status === "blocked" ? <ShieldAlert size={18} /> : <AlertTriangle size={18} />}
                    {status.label}
                  </div>
                  <p className="mt-1 text-xs leading-5 opacity-80">{status.detail}</p>
                </div>
                <button
                  type="button"
                  onClick={onRefresh}
                  disabled={loading}
                  className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-white px-3 text-xs font-semibold text-gray-700 shadow-sm disabled:opacity-50"
                >
                  {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                  重新检查
                </button>
              </div>

              <section aria-labelledby="training-summary-heading">
                <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-end">
                  <div>
                    <h3 id="training-summary-heading" className="text-sm font-semibold text-ink">训练准备摘要</h3>
                    <p className="mt-1 text-xs text-gray-500">{report.task_label} · 当前范围 {report.scoped_sample_count} 个样本</p>
                  </div>
                  <p className="text-xs text-gray-400">点击数字可回到对应样本范围</p>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <SummaryButton
                    label={classificationTask ? "已分类样本" : "有对象完成"}
                    value={report.completed_sample_count - report.confirmed_empty_sample_count}
                    detail={classificationTask ? "查看已有样本标签" : "查看已完成且有对象的图片"}
                    onClick={onShowCompleted}
                  />
                  <SummaryButton
                    label={classificationTask ? "待分类样本" : "确认空样本"}
                    value={classificationTask ? report.pending_sample_count : report.confirmed_empty_sample_count}
                    detail={classificationTask ? "查看尚无样本标签的数据" : "查看已确认没有目标的图片"}
                    onClick={onShowEmpty}
                  />
                  <SummaryButton
                    label="待审核"
                    value={report.pending_review_count}
                    detail="查看已经进入审核队列的样本"
                    onClick={onShowReview}
                  />
                  <SummaryButton
                    label="阻止导出"
                    value={report.blocking_issue_count}
                    detail="查看必须先处理的质量问题"
                    onClick={onOpenQuality}
                    tone={report.blocking_issue_count > 0 ? "danger" : "default"}
                  />
                </div>
              </section>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(260px,0.75fr)]">
                <section className="rounded-xl border border-line bg-white p-4" aria-labelledby="split-coverage-heading">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 id="split-coverage-heading" className="flex items-center gap-2 text-sm font-semibold text-ink">
                        <GitBranch size={17} />
                        split 覆盖
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">
                        已划分 {report.split_covered_sample_count} / {report.scoped_sample_count}（{report.split_coverage_percent}%）
                      </p>
                    </div>
                    <button type="button" onClick={onOpenSplitPlan} className="text-xs font-semibold text-gray-700 hover:text-black">配置划分</button>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {splitOrder.map((split) => (
                      <button
                        key={split}
                        type="button"
                        onClick={() => onShowSplit(split)}
                        className="rounded-lg bg-gray-50 px-3 py-3 text-left transition hover:bg-gray-100"
                      >
                        <div className="text-xs text-gray-500">{split === "unassigned" ? "未划分" : split}</div>
                        <div className="mt-1 text-lg font-semibold text-ink">{report.split_counts[split] ?? 0}</div>
                      </button>
                    ))}
                  </div>
                </section>

                <section className="rounded-xl border border-line bg-gray-50 p-4" aria-labelledby="format-recommendation-heading">
                  <h3 id="format-recommendation-heading" className="flex items-center gap-2 text-sm font-semibold text-ink">
                    <FileOutput size={17} />
                    推荐训练格式
                  </h3>
                  <div className="mt-3 rounded-lg bg-white px-3 py-3">
                    <div className="text-sm font-semibold text-ink">{formatCopy[report.recommended_export_format] ?? report.recommended_export_format}</div>
                    <div className="mt-1 text-xs text-gray-500">根据当前任务类型自动推荐</div>
                  </div>
                  <p className="mt-3 text-xs leading-5 text-gray-500">
                    兼容格式：{report.compatible_export_formats.map((format) => formatCopy[format] ?? format).join("、")}
                  </p>
                  <p className="mt-2 text-xs text-gray-400">
                    最近导出：{report.last_export_at ? new Date(report.last_export_at).toLocaleString() : "尚无记录"}
                  </p>
                </section>
              </div>

              <div className="rounded-xl border border-line bg-white p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <ClipboardCheck size={17} />
                  问题影响
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">阻止导出：{report.blocking_issue_count}</div>
                  <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">建议修复：{report.suggested_fix_count}</div>
                  <div className="rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">仅提示：{report.notice_count}</div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-line bg-gray-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <button type="button" onClick={onOpenQuality} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-gray-700 hover:bg-gray-50">
            <ClipboardCheck size={16} />
            查看质量问题
          </button>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button type="button" onClick={onOpenSplitPlan} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-gray-700 hover:bg-gray-50">
              <GitBranch size={16} />
              配置划分
            </button>
            <button type="button" onClick={onOpenExport} disabled={!report} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:bg-gray-300">
              继续选择导出
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
