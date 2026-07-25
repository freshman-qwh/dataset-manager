import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  Download,
  FileOutput,
  GitBranch,
  Info,
  Loader2,
  RefreshCw,
  SearchCheck,
  ShieldAlert,
  Wrench
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { downloadAnnotationExport, precheckAnnotationExport } from "../api/client";
import type {
  AnnotationExportFormat,
  AnnotationExportIssue,
  AnnotationExportPrecheckResponse,
  AnnotationExportSampleQuery
} from "../types/annotationExport";
import type {
  QualityIssue,
  QualityIssueSeverity,
  TrainingReadinessReport,
  TrainingReadinessStatus
} from "../types/dataset";
import Modal from "./Modal";

type ReadinessStep = 1 | 2 | 3 | 4;
type ExportScope = "filtered" | "all" | "split" | "selected";

interface TrainingReadinessModalProps {
  datasetId: number;
  open: boolean;
  report: TrainingReadinessReport | null;
  loading: boolean;
  error: string | null;
  currentQuery: AnnotationExportSampleQuery;
  selectedSampleIds: number[];
  onClose: () => void;
  onRefresh: () => void;
  onShowCompleted: () => void;
  onShowEmpty: () => void;
  onShowReview: () => void;
  onShowSplit: (split: string) => void;
  onOpenQuality: () => void;
  onOpenIssue: (issue: QualityIssue) => void;
  onOpenSplitPlan: () => void;
  onExportClassification: () => void;
}

const STEPS: Array<{ number: ReadinessStep; label: string; hint: string }> = [
  { number: 1, label: "检查", hint: "查看准备摘要" },
  { number: 2, label: "修复", hint: "理解问题影响" },
  { number: 3, label: "确认", hint: "选择范围与格式" },
  { number: 4, label: "导出", hint: "预检并下载" }
];

const READINESS_COPY: Record<TrainingReadinessStatus, {
  label: string;
  detail: string;
  classes: string;
}> = {
  blocked: {
    label: "存在导出阻断",
    detail: "请先处理阻断问题，再确认数据范围与训练格式。",
    classes: "border-red-200 bg-red-50 text-red-800"
  },
  needs_attention: {
    label: "建议先完善",
    detail: "可以继续确认导出选项，但仍有样本、审核或划分事项值得处理。",
    classes: "border-amber-200 bg-amber-50 text-amber-800"
  },
  ready: {
    label: "可以准备导出",
    detail: "主要检查已经通过，请确认数据范围和训练格式。",
    classes: "border-emerald-200 bg-emerald-50 text-emerald-800"
  }
};

const FORMAT_OPTIONS: Record<AnnotationExportFormat, {
  label: string;
  description: string;
}> = {
  coco_detection: {
    label: "COCO 检测",
    description: "通用检测训练格式，集中保存类别、边界框和图像信息。"
  },
  yolo_detection: {
    label: "YOLO 检测",
    description: "每张图对应一个归一化边界框标签文件，适合 YOLO 系列训练。"
  },
  voc: {
    label: "Pascal VOC",
    description: "使用 XML 保存边界框，适合传统检测工具链。"
  },
  coco_segmentation: {
    label: "COCO 分割",
    description: "集中保存多边形轮廓；矩形会转换成四点多边形。"
  },
  yolo_segmentation: {
    label: "YOLO 分割",
    description: "每张图保存归一化多边形顶点，适合 YOLO 分割训练。"
  },
  labelme: {
    label: "LabelMe JSON",
    description: "最大程度保留矩形、多边形和点等原始标注形状。"
  }
};

const ISSUE_COPY: Record<QualityIssueSeverity, {
  label: string;
  detail: string;
  empty: string;
  classes: string;
}> = {
  error: {
    label: "阻断导出",
    detail: "会造成训练数据不可用或语义不可靠，必须先处理。",
    empty: "没有发现阻断问题。",
    classes: "border-red-200 bg-red-50 text-red-800"
  },
  warning: {
    label: "建议修复",
    detail: "不会直接阻止导出，但可能降低训练质量或覆盖度。",
    empty: "没有需要优先完善的事项。",
    classes: "border-amber-200 bg-amber-50 text-amber-800"
  },
  info: {
    label: "仅作提醒",
    detail: "用于帮助理解当前数据状态，不影响导出。",
    empty: "没有额外提醒。",
    classes: "border-blue-200 bg-blue-50 text-blue-800"
  }
};

const EXPORT_FORMATS = Object.keys(FORMAT_OPTIONS) as AnnotationExportFormat[];

function isAnnotationExportFormat(value: string): value is AnnotationExportFormat {
  return EXPORT_FORMATS.includes(value as AnnotationExportFormat);
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

function precheckIssueMessage(issue: AnnotationExportIssue) {
  const messages: Record<string, string> = {
    NO_IMAGE_SAMPLES: "当前范围内没有可导出的图片，请调整筛选条件或样本范围。",
    CONFIRMED_EMPTY_SAMPLE_SKIPPED: "这是已确认无目标的图片，当前未启用“包含确认空样本”，因此不会写入导出结果。",
    UNFINISHED_SAMPLE_SKIPPED: "该样本尚未完成标注且没有对象，本次导出会跳过。",
    IMAGE_SIZE_UNAVAILABLE: "无法读取图片宽高，请检查文件是否完整且可访问。",
    EMPTY_CLASS_MAP: "没有可用于生成类别映射的有效标注标签。",
    NO_EXPORTABLE_OBJECTS: "所选格式下没有可导出的标注对象，请调整格式、范围或标注内容。",
    SPLIT_LEAKAGE: "相同文件内容出现在多个训练划分中，可能造成评估数据泄漏。",
    UNSUPPORTED_FILE_TYPE: "标注训练格式只支持图片样本，请调整当前文件类型筛选。",
    ANNOTATION_LABEL_REQUIRED: "标注对象缺少类别名称，补充类别后才能导出。",
    INVALID_CLASS_NAME: "类别名称包含不支持的控制字符，请修改后重试。",
    POLYGON_TO_BBOX: "多边形将转换为外接矩形框，轮廓细节不会保留。",
    RECTANGLE_TO_POLYGON: "矩形将转换为四点多边形后导出。",
    UNSUPPORTED_EXPORT_FORMAT: "当前训练格式不受支持，请选择其他格式。",
    COORDINATES_OUT_OF_BOUNDS: "标注坐标超出图片边界，请修正几何位置。",
    INVALID_GEOMETRY: "标注几何无效，请返回标注工作区检查顶点和形状。",
    INCOMPATIBLE_SHAPE_SKIPPED: "该标注形状与所选训练格式不兼容，本次会跳过。"
  };
  return messages[issue.code] ?? issue.message;
}

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
      <div className={`mt-1 text-xs leading-5 ${tone === "danger" ? "text-red-600" : "text-gray-500"}`}>{detail}</div>
    </button>
  );
}

function IssueIcon({ severity }: { severity: QualityIssueSeverity }) {
  if (severity === "error") {
    return <ShieldAlert size={17} className="shrink-0 text-red-600" />;
  }
  if (severity === "warning") {
    return <Wrench size={17} className="shrink-0 text-amber-600" />;
  }
  return <Info size={17} className="shrink-0 text-blue-600" />;
}

export default function TrainingReadinessModal({
  datasetId,
  open,
  report,
  loading,
  error,
  currentQuery,
  selectedSampleIds,
  onClose,
  onRefresh,
  onShowCompleted,
  onShowEmpty,
  onShowReview,
  onShowSplit,
  onOpenQuality,
  onOpenIssue,
  onOpenSplitPlan,
  onExportClassification
}: TrainingReadinessModalProps) {
  const [step, setStep] = useState<ReadinessStep>(1);
  const [format, setFormat] = useState<AnnotationExportFormat>("labelme");
  const [scope, setScope] = useState<ExportScope>("filtered");
  const [selectedSplit, setSelectedSplit] = useState("train");
  const [includeEmpty, setIncludeEmpty] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [precheck, setPrecheck] = useState<AnnotationExportPrecheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const classificationTask = report?.task_type === "classification";
  const status = report ? READINESS_COPY[report.status] : null;
  const compatibleFormats = useMemo(
    () => (report?.compatible_export_formats ?? []).filter(isAnnotationExportFormat),
    [report?.compatible_export_formats]
  );
  const advancedFormats = useMemo(
    () => (report?.advanced_export_formats ?? []).filter(isAnnotationExportFormat),
    [report?.advanced_export_formats]
  );
  const sampleQuery = useMemo<AnnotationExportSampleQuery>(() => {
    if (scope === "all") {
      return { sort_by: "relative_path", sort_order: "asc" };
    }
    if (scope === "split") {
      return { split: selectedSplit, sort_by: "relative_path", sort_order: "asc" };
    }
    if (scope === "selected") {
      return { sample_ids: selectedSampleIds, sort_by: "relative_path", sort_order: "asc" };
    }
    return currentQuery;
  }, [currentQuery, scope, selectedSampleIds, selectedSplit]);

  useEffect(() => {
    if (!open) {
      setChecking(false);
      setDownloading(false);
      return;
    }
    setStep(1);
    setScope("filtered");
    setSelectedSplit("train");
    setIncludeEmpty(false);
    setShowAdvanced(false);
    setPrecheck(null);
    setExportError(null);
  }, [open]);

  useEffect(() => {
    if (report && isAnnotationExportFormat(report.recommended_export_format)) {
      setFormat(report.recommended_export_format);
    }
  }, [report]);

  useEffect(() => {
    setPrecheck(null);
    setExportError(null);
  }, [format, includeEmpty, sampleQuery]);

  async function runPrecheck() {
    if (classificationTask) {
      setStep(4);
      return;
    }
    if (scope === "selected" && selectedSampleIds.length === 0) {
      setExportError("请先在样本列表中选择至少一个样本。");
      return;
    }
    setStep(4);
    setChecking(true);
    setExportError(null);
    try {
      setPrecheck(await precheckAnnotationExport(datasetId, {
        format,
        sample_query: sampleQuery,
        include_empty: includeEmpty
      }));
    } catch {
      setPrecheck(null);
      setExportError("导出预检失败，请确认后端服务可用后重试。");
    } finally {
      setChecking(false);
    }
  }

  function goToStep(nextStep: ReadinessStep) {
    if (nextStep === 4) {
      void runPrecheck();
      return;
    }
    setStep(nextStep);
  }

  async function handleDownload() {
    if (!precheck || precheck.blocked) {
      return;
    }
    setDownloading(true);
    setExportError(null);
    try {
      const result = await downloadAnnotationExport(datasetId, format, sampleQuery, includeEmpty);
      triggerDownload(result.blob, result.filename);
      onClose();
    } catch {
      setExportError("导出失败，数据可能在预检后发生变化，请重新运行预检。");
      setPrecheck(null);
    } finally {
      setDownloading(false);
    }
  }

  function renderSummary() {
    if (!report || !status) {
      return null;
    }
    const splitOrder = ["train", "val", "test", "unassigned"];
    return (
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
            <p className="text-xs text-gray-400">点击数字可查看对应样本</p>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryButton
              label={classificationTask ? "已分类样本" : "有对象完成"}
              value={classificationTask ? report.completed_sample_count : report.completed_sample_count - report.confirmed_empty_sample_count}
              detail={classificationTask ? "查看已有样本标签的数据" : "查看已完成且包含对象的图片"}
              onClick={onShowCompleted}
            />
            <SummaryButton
              label={classificationTask ? "待分类样本" : "确认空样本"}
              value={classificationTask ? report.pending_sample_count : report.confirmed_empty_sample_count}
              detail={classificationTask ? "查看尚无样本标签的数据" : "查看已确认没有目标的图片"}
              onClick={onShowEmpty}
            />
            <SummaryButton label="待审核" value={report.pending_review_count} detail="查看已进入审核队列的样本" onClick={onShowReview} />
            <SummaryButton
              label="阻断导出"
              value={report.blocking_issue_count}
              detail="查看必须先处理的质量问题"
              onClick={() => setStep(2)}
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
              <div className="text-sm font-semibold text-ink">
                {classificationTask ? "CSV 标签表" : FORMAT_OPTIONS[format]?.label ?? report.recommended_export_format}
              </div>
              <div className="mt-1 text-xs text-gray-500">根据当前任务类型自动推荐，下一步仍可调整</div>
            </div>
            <p className="mt-3 text-xs text-gray-400">
              最近导出：{report.last_export_at ? new Date(report.last_export_at).toLocaleString() : "尚无记录"}
            </p>
          </section>
        </div>
      </div>
    );
  }

  function renderIssues() {
    if (!report) {
      return null;
    }
    const severities: QualityIssueSeverity[] = ["error", "warning", "info"];
    const visibleIssues = report.issues ?? [];
    return (
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">先理解问题会造成什么影响</h3>
          <p className="mt-1 text-xs leading-5 text-gray-500">问题按照对训练导出的实际影响分组。技术错误码保留在详情中，方便定位和复现。</p>
        </div>
        {severities.map((severity) => {
          const copy = ISSUE_COPY[severity];
          const issues = visibleIssues.filter((issue) => issue.severity === severity);
          const count = severity === "error"
            ? report.blocking_issue_count
            : severity === "warning"
              ? report.suggested_fix_count
              : report.notice_count;
          return (
            <section key={severity} className={`rounded-xl border p-4 ${copy.classes}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="flex items-center gap-2 text-sm font-semibold">
                    <IssueIcon severity={severity} />
                    {copy.label}
                  </h3>
                  <p className="mt-1 text-xs leading-5 opacity-80">{copy.detail}</p>
                </div>
                <span className="rounded-full bg-white/80 px-2.5 py-1 text-xs font-semibold">{count}</span>
              </div>
              {issues.length === 0 ? (
                <div className="mt-3 rounded-lg bg-white/70 px-3 py-3 text-xs opacity-80">
                  {!report.issues && count > 0 ? "问题明细暂未加载，可打开完整质量报告查看。" : copy.empty}
                </div>
              ) : (
                <div className="mt-3 space-y-2">
                  {issues.map((issue, index) => (
                    <button
                      key={`${issue.code}-${issue.annotation_id ?? issue.sample_id ?? index}`}
                      type="button"
                      onClick={() => issue.sample_id ? onOpenIssue(issue) : onOpenQuality()}
                      className="flex w-full items-start justify-between gap-3 rounded-lg bg-white/80 px-3 py-3 text-left text-gray-700 transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-ink">{issue.title}</div>
                        <div className="mt-1 text-xs leading-5 text-gray-600">
                          {issue.sample_path ? `${issue.sample_path}：` : ""}{issue.message}
                        </div>
                        <div className="mt-1 font-mono text-[11px] text-gray-400">{issue.code}</div>
                      </div>
                      <ArrowRight size={15} className="mt-1 shrink-0 text-gray-400" />
                    </button>
                  ))}
                </div>
              )}
            </section>
          );
        })}
        {(report.truncated_issue_count ?? 0) > 0 && (
          <button type="button" onClick={onOpenQuality} className="w-full rounded-lg border border-line bg-white px-3 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50">
            另有 {report.truncated_issue_count ?? 0} 条问题未在此显示，查看完整质量报告
          </button>
        )}
      </div>
    );
  }

  function renderConfirmation() {
    if (!report) {
      return null;
    }
    if (classificationTask) {
      return (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-ink">确认分类训练数据</h3>
            <p className="mt-1 text-xs leading-5 text-gray-500">分类任务将导出整个数据集的 CSV 标签表，包含相对路径、样本标签与 split。</p>
          </div>
          <div className="rounded-xl border border-gray-900 bg-gray-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-ink">CSV 标签表</div>
                <p className="mt-1 text-xs text-gray-500">{report.scoped_sample_count} 个样本 · 当前推荐格式</p>
              </div>
              <CheckCircle2 size={20} className="text-emerald-600" />
            </div>
          </div>
          <div className="rounded-xl border border-line bg-white p-4 text-xs leading-5 text-gray-600">
            导出不会修改原始文件。阻断问题会在最后一步提示，建议先完成缺失标签或不可用文件的修复。
          </div>
        </div>
      );
    }
    return (
      <div className="space-y-5">
        <section aria-labelledby="training-export-format">
          <h3 id="training-export-format" className="text-sm font-semibold text-ink">选择训练格式</h3>
          <p className="mt-1 text-xs leading-5 text-gray-500">优先展示与当前任务语义兼容的格式；高级格式可能发生形状转换。</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {compatibleFormats.map((candidate) => {
              const option = FORMAT_OPTIONS[candidate];
              const selected = format === candidate;
              return (
                <button
                  key={candidate}
                  type="button"
                  onClick={() => setFormat(candidate)}
                  className={`rounded-xl border p-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 ${
                    selected ? "border-gray-900 bg-gray-50 shadow-sm" : "border-line bg-white hover:border-gray-300"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-ink">{option.label}</span>
                    {selected && <Check size={17} className="text-gray-900" />}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-gray-500">{option.description}</p>
                  {candidate === report.recommended_export_format && (
                    <span className="mt-3 inline-flex rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700">推荐</span>
                  )}
                </button>
              );
            })}
          </div>
          {advancedFormats.length > 0 && (
            <div className="mt-3 rounded-xl border border-line bg-white">
              <button
                type="button"
                onClick={() => setShowAdvanced((visible) => !visible)}
                aria-expanded={showAdvanced}
                className="flex min-h-11 w-full items-center justify-between gap-3 px-4 text-left text-sm font-semibold text-gray-700"
              >
                高级格式（{advancedFormats.length}）
                <ChevronDown size={17} className={`transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
              </button>
              {showAdvanced && (
                <div className="grid gap-2 border-t border-line p-3 sm:grid-cols-2">
                  {advancedFormats.map((candidate) => {
                    const option = FORMAT_OPTIONS[candidate];
                    const selected = format === candidate;
                    return (
                      <button
                        key={candidate}
                        type="button"
                        onClick={() => setFormat(candidate)}
                        className={`rounded-lg border p-3 text-left ${
                          selected ? "border-gray-900 bg-gray-50" : "border-line hover:border-gray-300"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 text-sm font-medium text-ink">
                          {option.label}
                          {selected && <Check size={15} />}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-gray-500">{option.description}</p>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </section>

        <section aria-labelledby="training-export-scope">
          <h3 id="training-export-scope" className="text-sm font-semibold text-ink">确认样本范围</h3>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {([
              ["filtered", "当前筛选结果", "使用页面中正在查看的筛选条件"],
              ["all", "全部图片", "忽略页面筛选，导出所有图片"],
              ["split", "指定 split", "只导出 train、val、test 或未划分样本"],
              ["selected", `已选样本（${selectedSampleIds.length}）`, "只导出样本列表中已选择的图片"]
            ] as Array<[ExportScope, string, string]>).map(([value, label, description]) => (
              <button
                key={value}
                type="button"
                onClick={() => setScope(value)}
                className={`rounded-xl border p-3 text-left ${
                  scope === value ? "border-gray-900 bg-gray-50" : "border-line bg-white hover:border-gray-300"
                }`}
              >
                <div className="flex items-center justify-between gap-2 text-sm font-medium text-ink">
                  {label}
                  {scope === value && <Check size={15} />}
                </div>
                <p className="mt-1 text-xs leading-5 text-gray-500">{description}</p>
              </button>
            ))}
          </div>
          {scope === "split" && (
            <label className="mt-3 block text-sm text-gray-700" htmlFor="training-export-split">
              选择 split
              <select
                id="training-export-split"
                value={selectedSplit}
                onChange={(event) => setSelectedSplit(event.target.value)}
                className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:border-gray-900 focus:ring-2 focus:ring-gray-200"
              >
                <option value="train">train</option>
                <option value="val">val</option>
                <option value="test">test</option>
                <option value="unassigned">未划分</option>
              </select>
            </label>
          )}
          <label className="mt-3 flex items-start gap-3 rounded-xl border border-line bg-white px-3 py-3 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeEmpty}
              onChange={(event) => setIncludeEmpty(event.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300"
            />
            <span>
              包含确认空样本
              <span className="mt-1 block text-xs leading-5 text-gray-500">启用后会为没有目标的图片生成空记录或空标签文件。</span>
            </span>
          </label>
          {scope === "selected" && selectedSampleIds.length === 0 && (
            <div role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              当前没有已选样本，请返回样本列表选择，或改用其他范围。
            </div>
          )}
        </section>
      </div>
    );
  }

  function renderExport() {
    if (!report) {
      return null;
    }
    if (classificationTask) {
      const blocked = report.blocking_issue_count > 0;
      return (
        <div className="space-y-4">
          <div className={`rounded-xl border p-4 ${blocked ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
            <div className="flex items-start gap-3">
              {blocked ? <ShieldAlert size={20} /> : <CheckCircle2 size={20} />}
              <div>
                <div className="text-sm font-semibold">{blocked ? "存在阻断问题，暂不能导出" : "检查通过，可以生成 CSV"}</div>
                <p className="mt-1 text-xs leading-5 opacity-80">
                  {blocked ? `请先处理 ${report.blocking_issue_count} 个阻断问题。` : `将导出 ${report.scoped_sample_count} 个分类样本的标签和划分信息。`}
                </p>
              </div>
            </div>
          </div>
          {blocked && (
            <button type="button" onClick={() => setStep(2)} className="w-full rounded-lg border border-line bg-white px-4 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50">
              返回查看阻断问题
            </button>
          )}
        </div>
      );
    }
    return (
      <div className="space-y-4" aria-live="polite">
        {checking && (
          <div className="flex min-h-56 items-center justify-center gap-2 text-sm text-gray-500">
            <Loader2 size={19} className="animate-spin" />
            正在检查所选范围与格式
          </div>
        )}
        {!checking && exportError && (
          <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">
            <div className="flex items-start gap-3">
              <AlertTriangle size={19} className="shrink-0" />
              <div className="min-w-0">
                <div className="text-sm font-semibold">预检未完成</div>
                <p className="mt-1 text-xs leading-5">{exportError}</p>
                <button type="button" onClick={() => void runPrecheck()} className="mt-3 inline-flex min-h-9 items-center gap-2 rounded-lg bg-white px-3 text-xs font-semibold shadow-sm">
                  <RefreshCw size={14} />
                  重试预检
                </button>
              </div>
            </div>
          </div>
        )}
        {!checking && precheck && (
          <>
            <div className={`rounded-xl border p-4 ${precheck.blocked ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
              <div className="flex items-start gap-3">
                {precheck.blocked ? <ShieldAlert size={20} /> : <CheckCircle2 size={20} />}
                <div>
                  <div className="text-sm font-semibold">{precheck.blocked ? "存在阻断问题，暂不能导出" : "导出预检通过"}</div>
                  <p className="mt-1 text-xs leading-5 opacity-80">
                    {precheck.sample_count} 张图片 · {precheck.exportable_object_count} 个可导出对象 · {precheck.skipped_object_count} 个对象跳过
                  </p>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-2 text-red-700">阻断 {precheck.error_count}</div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-2 py-2 text-amber-700">建议 {precheck.warning_count}</div>
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-2 py-2 text-blue-700">提醒 {precheck.info_count}</div>
            </div>
            {precheck.class_map.length > 0 && (
              <section className="rounded-xl border border-line bg-white p-4">
                <h3 className="text-xs font-semibold text-gray-700">类别映射</h3>
                <div className="mt-2 flex flex-wrap gap-2">
                  {precheck.class_map.map((item) => (
                    <span key={item.name} className="rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-700">{item.yolo_id}: {item.name}</span>
                  ))}
                </div>
              </section>
            )}
            {precheck.issues.length > 0 && (
              <section className="rounded-xl border border-line bg-white p-3">
                <h3 className="px-1 text-xs font-semibold text-gray-700">预检明细</h3>
                <div className="mt-2 max-h-64 space-y-2 overflow-y-auto">
                  {precheck.issues.map((issue, index) => (
                    <div key={`${issue.code}-${issue.annotation_id ?? issue.sample_id ?? index}`} className="flex gap-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-700">
                      <IssueIcon severity={issue.severity} />
                      <div className="min-w-0">
                        <div className="break-words font-medium leading-5 text-ink">
                          {issue.sample_path ? `${issue.sample_path}：` : ""}{precheckIssueMessage(issue)}
                        </div>
                        <div className="mt-1 font-mono text-[11px] text-gray-400">{issue.code}</div>
                      </div>
                    </div>
                  ))}
                  {precheck.truncated_issue_count > 0 && (
                    <div className="px-2 py-1 text-xs text-gray-500">另有 {precheck.truncated_issue_count} 条预检明细未显示。</div>
                  )}
                </div>
              </section>
            )}
          </>
        )}
        {!checking && !precheck && !exportError && (
          <button type="button" onClick={() => void runPrecheck()} className="flex min-h-52 w-full flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50 text-sm font-semibold text-gray-700 hover:bg-gray-100">
            <SearchCheck size={24} className="mb-3 text-gray-500" />
            运行导出预检
          </button>
        )}
      </div>
    );
  }

  const canContinue = Boolean(report) && !(step === 3 && scope === "selected" && selectedSampleIds.length === 0);
  const classificationBlocked = classificationTask && Boolean(report?.blocking_issue_count);

  return (
    <Modal open={open} title="准备训练" onClose={onClose} size="xl">
      <div className="flex max-h-[84vh] min-h-[34rem] flex-col">
        <div className="border-b border-line px-4 py-4 sm:px-5">
          <ol className="grid grid-cols-4 gap-1 sm:gap-2" aria-label="训练准备步骤">
            {STEPS.map((item, index) => (
              <li key={item.number} className="flex min-w-0 items-center gap-1 sm:gap-2">
                <button
                  type="button"
                  onClick={() => goToStep(item.number)}
                  aria-current={step === item.number ? "step" : undefined}
                  aria-label={`${item.number} ${item.label}：${item.hint}`}
                  title={item.hint}
                  disabled={!report}
                  className="group flex min-w-0 items-center gap-1.5 rounded-lg px-1 py-1 text-left disabled:cursor-not-allowed"
                >
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                    step === item.number ? "bg-gray-900 text-white" : step > item.number ? "bg-emerald-100 text-emerald-700" : "bg-gray-100 text-gray-500"
                  }`}>
                    {step > item.number ? <Check size={14} /> : item.number}
                  </span>
                  <span className={`hidden truncate text-xs font-medium min-[430px]:block ${step === item.number ? "text-ink" : "text-gray-500"}`}>{item.label}</span>
                </button>
                {index < STEPS.length - 1 && <span className={`h-px min-w-1 flex-1 ${step > item.number ? "bg-emerald-200" : "bg-line"}`} />}
              </li>
            ))}
          </ol>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-5">
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
          {report && step === 1 && renderSummary()}
          {report && step === 2 && renderIssues()}
          {report && step === 3 && renderConfirmation()}
          {report && step === 4 && renderExport()}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-line bg-gray-50 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <button
            type="button"
            onClick={() => step > 1 ? setStep((step - 1) as ReadinessStep) : onClose()}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            {step > 1 && <ArrowLeft size={16} />}
            {step > 1 ? "上一步" : "稍后再说"}
          </button>
          <div className="flex flex-col gap-2 sm:flex-row">
            {step === 2 && (
              <button type="button" onClick={onOpenQuality} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-gray-700 hover:bg-gray-50">
                <ClipboardCheck size={16} />
                完整质量报告
              </button>
            )}
            {step < 4 && (
              <button
                type="button"
                onClick={() => goToStep((step + 1) as ReadinessStep)}
                disabled={!canContinue}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {step === 3 ? "运行预检" : "继续"}
                {step === 3 ? <SearchCheck size={16} /> : <ArrowRight size={16} />}
              </button>
            )}
            {step === 4 && classificationTask && (
              <button
                type="button"
                onClick={onExportClassification}
                disabled={classificationBlocked}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                <Download size={16} />
                生成 CSV
              </button>
            )}
            {step === 4 && !classificationTask && (
              <button
                type="button"
                onClick={() => void handleDownload()}
                disabled={!precheck || precheck.blocked || checking || downloading}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {downloading ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
                {downloading ? "生成中" : "确认并下载"}
              </button>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
