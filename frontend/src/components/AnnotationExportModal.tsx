import axios from "axios";
import { AlertTriangle, CheckCircle2, Download, Info, LoaderCircle, SearchCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  createAnnotationExportJob,
  downloadAnnotationExport,
  downloadJobArtifact,
  getJob,
  listJobs,
  precheckAnnotationExport,
  recordTrainingExport,
  saveTrainingReadinessConfig
} from "../api/client";
import type {
  AnnotationExportFormat,
  AnnotationExportJobCreateRequest,
  AnnotationExportPrecheckResponse,
  AnnotationExportSampleQuery
} from "../types/annotationExport";
import type { TrainingReadinessConfigInput } from "../types/dataset";
import type { Job } from "../types/job";
import { uiCopy } from "../utils/uiCopy";
import Modal from "./Modal";

type ExportScope = "filtered" | "all" | "split" | "selected";

interface AnnotationExportModalProps {
  datasetId: number;
  open: boolean;
  defaultFormat?: AnnotationExportFormat;
  currentQuery: AnnotationExportSampleQuery;
  selectedSampleIds: number[];
  onClose: () => void;
}

const FORMAT_OPTIONS: Array<{
  value: AnnotationExportFormat;
  label: string;
  description: string;
}> = [
  {
    value: "labelme",
    label: "LabelMe JSON",
    description: "保留 rectangle、polygon、point 和 points，导出 annotations/*.json。"
  },
  {
    value: "coco_detection",
    label: "COCO detection",
    description: "导出 bbox；polygon 会有损转换为外接框。"
  },
  {
    value: "coco_segmentation",
    label: "COCO segmentation",
    description: "导出 polygon 顶点；rectangle 转四点 polygon，暂不支持 RLE mask。"
  },
  {
    value: "yolo_detection",
    label: "YOLO detection",
    description: "导出归一化 bbox；polygon 会有损转换为外接框。"
  },
  {
    value: "yolo_segmentation",
    label: "YOLO segmentation",
    description: "导出归一化 polygon 顶点；不需要 brush 或 mask。"
  },
  {
    value: "voc",
    label: "Pascal VOC",
    description: "导出 XML bbox；polygon 会有损转换为外接框。"
  }
];

type TaskExportFormat = AnnotationExportJobCreateRequest["format"];

const EXPORT_STAGE_COPY: Record<string, string> = {
  queued: "等待开始",
  prechecking: "导出预检",
  writing_archive: "写入导出包",
  writing_json: "写入 COCO JSON",
  finalizing: "校验导出产物",
  completed: "已完成"
};

function usesExportJob(format: AnnotationExportFormat): format is TaskExportFormat {
  return format === "labelme"
    || format === "coco_detection"
    || format === "coco_segmentation"
    || format === "yolo_detection"
    || format === "yolo_segmentation"
    || format === "voc";
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

function stableSerialize(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableSerialize).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined && item !== null)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableSerialize(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function jobMatchesRequest(
  job: Job,
  format: TaskExportFormat,
  query: AnnotationExportSampleQuery,
  includeEmpty: boolean
): boolean {
  return job.job_type === "annotation.export"
    && job.parameters.format === format
    && job.parameters.include_empty === includeEmpty
    && stableSerialize(job.parameters.sample_query) === stableSerialize(query);
}

export default function AnnotationExportModal({
  datasetId,
  open,
  defaultFormat = "labelme",
  currentQuery,
  selectedSampleIds,
  onClose
}: AnnotationExportModalProps) {
  const [format, setFormat] = useState<AnnotationExportFormat>(defaultFormat);
  const [scope, setScope] = useState<ExportScope>("filtered");
  const [selectedSplit, setSelectedSplit] = useState("train");
  const [includeEmpty, setIncludeEmpty] = useState(false);
  const [precheck, setPrecheck] = useState<AnnotationExportPrecheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadCompleted, setDownloadCompleted] = useState(false);
  const [exportJob, setExportJob] = useState<Job | null>(null);
  const [compatibilityNotice, setCompatibilityNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const exportJobId = exportJob?.id ?? null;
  const exportJobStatus = exportJob?.status ?? null;

  const selectedFormat = useMemo(
    () => FORMAT_OPTIONS.find((item) => item.value === format) ?? FORMAT_OPTIONS[0],
    [format]
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
    setPrecheck(null);
    setDownloadCompleted(false);
    setExportJob(null);
    setCompatibilityNotice(null);
    setError(null);
  }, [format, includeEmpty, sampleQuery]);

  useEffect(() => {
    if (!open) {
      setChecking(false);
      setDownloading(false);
      return;
    }
    setFormat(defaultFormat);
    setPrecheck(null);
    setDownloadCompleted(false);
    setCompatibilityNotice(null);
    setError(null);
  }, [defaultFormat, open]);

  useEffect(() => {
    if (!open || !usesExportJob(format)) return;
    let disposed = false;
    void listJobs(100, { datasetId, jobType: "annotation.export" })
      .then((response) => {
        if (disposed) return;
        const matching = response.items.find((job) => jobMatchesRequest(job, format, sampleQuery, includeEmpty));
        if (matching) setExportJob(matching);
      })
      .catch(() => {
        // An unmigrated database will use the synchronous compatibility path.
      });
    return () => {
      disposed = true;
    };
  }, [datasetId, format, includeEmpty, open, sampleQuery]);

  useEffect(() => {
    if (exportJobId === null || !exportJobStatus || !["queued", "running"].includes(exportJobStatus)) return;
    let disposed = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const job = await getJob(exportJobId);
        if (disposed) return;
        setExportJob(job);
        if (job.status === "queued" || job.status === "running") {
          timer = window.setTimeout(() => void poll(), 750);
        }
      } catch {
        if (!disposed) setError("导出任务状态读取失败，请在任务中心查看。");
      }
    };
    void poll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [exportJobId, exportJobStatus]);

  function trainingConfig(
    classMap: AnnotationExportPrecheckResponse["class_map"] = []
  ): TrainingReadinessConfigInput {
    return {
      format,
      scope,
      split: scope === "split" ? selectedSplit : null,
      include_empty: includeEmpty,
      sample_query: sampleQuery,
      class_map: classMap
    };
  }

  async function handlePrecheck() {
    if (scope === "selected" && selectedSampleIds.length === 0) {
      setError("请先在样本列表中选择至少一个样本。");
      return;
    }
    setChecking(true);
    setError(null);
    try {
      const result = await precheckAnnotationExport(datasetId, {
        format,
        sample_query: sampleQuery,
        include_empty: includeEmpty
      });
      setPrecheck(result);
      try {
        await saveTrainingReadinessConfig(datasetId, trainingConfig(result.class_map));
      } catch {
        setError("预检已完成，但未能保存本次训练配置。");
      }
    } catch {
      setError(`${uiCopy.exportCheck}失败，请确认后端服务可用。`);
    } finally {
      setChecking(false);
    }
  }

  async function handleDownload() {
    const taskExport = usesExportJob(format);
    const completedJobAvailable = taskExport && exportJob?.status === "succeeded";
    if ((!precheck || precheck.blocked) && !completedJobAvailable) {
      return;
    }
    setDownloading(true);
    setError(null);
    setCompatibilityNotice(null);
    try {
      if (taskExport) {
        if (exportJob?.status === "succeeded") {
          const result = await downloadJobArtifact(exportJob.id);
          triggerDownload(result.blob, result.filename);
          setDownloadCompleted(true);
          if (precheck) {
            try {
              await recordTrainingExport(datasetId, trainingConfig(precheck.class_map));
            } catch {
              setError("导出包已经下载，但训练就绪记录更新失败。");
            }
          }
          return;
        }
        const response = await createAnnotationExportJob(datasetId, {
          format,
          sample_query: sampleQuery,
          include_empty: includeEmpty
        });
        setExportJob(response.job);
        setDownloadCompleted(false);
        window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
        return;
      }
      if (!precheck) return;
      const result = await downloadAnnotationExport(datasetId, format, sampleQuery, includeEmpty);
      try {
        await recordTrainingExport(datasetId, trainingConfig(precheck.class_map));
      } catch {
        triggerDownload(result.blob, result.filename);
        setDownloadCompleted(true);
        setError("文件已经下载，但未能记录最近导出时间；下载内容不受影响。");
        return;
      }
      triggerDownload(result.blob, result.filename);
      onClose();
    } catch (caught) {
      if (taskExport && exportJob?.status === "succeeded") {
        setExportJob(null);
        setPrecheck(null);
        setError("导出产物已不可用，请重新运行导出检查并提交任务。");
        return;
      }
      if (
        taskExport
        && axios.isAxiosError(caught)
        && caught.response?.status === 409
      ) {
        if (!precheck) {
          setError("兼容导出需要重新运行导出预检。");
          return;
        }
        try {
          const result = await downloadAnnotationExport(datasetId, format, sampleQuery, includeEmpty);
          triggerDownload(result.blob, result.filename);
          setDownloadCompleted(true);
          setCompatibilityNotice("任务中心尚未启用，本次已使用兼容导出。");
          try {
            await recordTrainingExport(datasetId, trainingConfig(precheck.class_map));
          } catch {
            setError("文件已经下载，但未能记录最近导出时间；下载内容不受影响。");
          }
          return;
        } catch {
          setError("兼容导出失败，请重新运行导出预检。");
          setPrecheck(null);
          return;
        }
      }
      setError(`导出失败。数据可能在${uiCopy.exportCheck}后发生变化，请重新检查。`);
      setPrecheck(null);
    } finally {
      setDownloading(false);
    }
  }

  const exportJobActive = exportJob?.status === "queued" || exportJob?.status === "running";
  const exportJobFailed = exportJob?.status === "failed"
    || exportJob?.status === "cancelled"
    || exportJob?.status === "interrupted";
  const exportJobProgress = exportJob?.progress_total && exportJob.progress_total > 0
    ? Math.min(100, Math.round((exportJob.progress_current / exportJob.progress_total) * 100))
    : null;

  return (
    <Modal open={open} title="标注训练格式导出" onClose={onClose}>
      <div className="max-h-[82vh] space-y-5 overflow-y-auto px-5 py-5">
        <section className="space-y-3" aria-labelledby="annotation-export-options">
          <h3 id="annotation-export-options" className="text-sm font-semibold text-ink">
            1. 选择格式与范围
          </h3>
          <label className="block text-sm text-gray-700" htmlFor="annotation-export-format">
            导出格式
          </label>
          <select
            id="annotation-export-format"
            value={format}
            onChange={(event) => setFormat(event.target.value as AnnotationExportFormat)}
            className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 focus:ring-2 focus:ring-gray-200"
          >
            {FORMAT_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <p className="rounded-lg border border-line bg-gray-50 px-3 py-2 text-xs leading-5 text-gray-600">
            {selectedFormat.description}
          </p>

          <label className="block text-sm text-gray-700" htmlFor="annotation-export-scope">
            样本范围
          </label>
          <select
            id="annotation-export-scope"
            value={scope}
            onChange={(event) => setScope(event.target.value as ExportScope)}
            className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 focus:ring-2 focus:ring-gray-200"
          >
            <option value="filtered">当前筛选结果</option>
            <option value="all">全数据集图片</option>
            <option value="split">指定 split</option>
            <option value="selected">已选择样本（{selectedSampleIds.length}）</option>
          </select>

          {scope === "split" && (
            <div>
              <label className="block text-sm text-gray-700" htmlFor="annotation-export-split">
                Split
              </label>
              <select
                id="annotation-export-split"
                value={selectedSplit}
                onChange={(event) => setSelectedSplit(event.target.value)}
                className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 focus:ring-2 focus:ring-gray-200"
              >
                <option value="train">train</option>
                <option value="val">val</option>
                <option value="test">test</option>
                <option value="unassigned">未划分</option>
              </select>
            </div>
          )}

          <label className="flex items-start gap-3 rounded-lg border border-line px-3 py-3 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeEmpty}
              onChange={(event) => setIncludeEmpty(event.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300"
            />
            <span>
              包含{uiCopy.noTargetImage}
              <span className="mt-1 block text-xs leading-5 text-gray-500">
                默认跳过没有目标格式兼容对象的图片；启用后会生成空记录或空标签文件。
              </span>
            </span>
          </label>
        </section>

        <section className="space-y-3" aria-labelledby="annotation-export-precheck">
          <div className="flex items-center justify-between gap-3">
            <h3 id="annotation-export-precheck" className="text-sm font-semibold text-ink">
              2. 运行{uiCopy.exportCheck}
            </h3>
            <button
              type="button"
              onClick={() => void handlePrecheck()}
              disabled={checking || (scope === "selected" && selectedSampleIds.length === 0)}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              {checking ? <LoaderCircle size={16} className="animate-spin" /> : <SearchCheck size={16} />}
              {checking ? "检查中" : `运行${uiCopy.exportCheck}`}
            </button>
          </div>

          <div aria-live="polite">
            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            )}
            {precheck && (
              <div className="space-y-3">
                <div
                  className={`flex items-start gap-3 rounded-lg border px-3 py-3 ${
                    precheck.blocked
                      ? "border-red-200 bg-red-50 text-red-800"
                      : "border-emerald-200 bg-emerald-50 text-emerald-800"
                  }`}
                >
                  {precheck.blocked ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
                  <div>
                    <div className="text-sm font-medium">
                      {precheck.blocked ? "存在阻断问题，暂不能导出" : `${uiCopy.exportCheck}通过，可以导出`}
                    </div>
                    <div className="mt-1 text-xs leading-5">
                      {precheck.sample_count} 张图片，{precheck.exportable_object_count} 个可导出对象，
                      {precheck.skipped_object_count} 个对象跳过。
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-2 text-red-700">
                    Error {precheck.error_count}
                  </div>
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-2 py-2 text-amber-700">
                    Warning {precheck.warning_count}
                  </div>
                  <div className="rounded-lg border border-blue-200 bg-blue-50 px-2 py-2 text-blue-700">
                    Info {precheck.info_count}
                  </div>
                </div>

                {precheck.class_map.length > 0 && (
                  <div className="rounded-lg border border-line px-3 py-3">
                    <div className="text-xs font-medium text-gray-700">类别映射</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {precheck.class_map.map((item) => (
                        <span key={item.name} className="rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-700">
                          {item.yolo_id}: {item.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {precheck.issues.length > 0 && (
                  <div className="max-h-52 space-y-2 overflow-y-auto rounded-lg border border-line p-2">
                    {precheck.issues.slice(0, 50).map((issue, index) => (
                      <div key={`${issue.code}-${issue.annotation_id ?? issue.sample_id ?? index}`} className="flex gap-2 rounded-md bg-gray-50 px-2 py-2 text-xs text-gray-700">
                        {issue.severity === "info" ? (
                          <Info size={15} className="shrink-0 text-blue-600" />
                        ) : (
                          <AlertTriangle
                            size={15}
                            className={issue.severity === "error" ? "shrink-0 text-red-600" : "shrink-0 text-amber-600"}
                          />
                        )}
                        <div>
                          <div className="font-medium">{issue.code}</div>
                          <div className="mt-0.5 leading-5 text-gray-600">
                            {issue.sample_path ? `${issue.sample_path}：` : ""}
                            {issue.message}
                          </div>
                        </div>
                      </div>
                    ))}
                    {precheck.issues.length > 50 && (
                      <div className="px-2 py-1 text-xs text-gray-500">
                        当前仅显示前 50 条；另有 {precheck.issues.length - 50 + precheck.truncated_issue_count} 条未显示。
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
          {usesExportJob(format) && exportJob ? (
            <div
              aria-live="polite"
              className={`rounded-lg border px-3 py-3 text-sm ${
                exportJob.status === "succeeded"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : exportJobFailed
                    ? "border-amber-200 bg-amber-50 text-amber-800"
                    : "border-blue-200 bg-blue-50 text-blue-800"
              }`}
            >
              <div className="font-medium">
                {exportJob.status === "succeeded"
                  ? "导出产物已生成，可以下载"
                  : exportJobFailed
                    ? `任务${exportJob.status === "cancelled" ? "已取消" : exportJob.status === "interrupted" ? "已中断" : "失败"}，可以重新提交`
                    : "导出任务正在后台生成"}
              </div>
              <div className="mt-1 text-xs leading-5">
                {exportJobActive
                  ? `阶段：${EXPORT_STAGE_COPY[exportJob.stage] ?? exportJob.stage}${exportJobProgress !== null ? ` · ${exportJobProgress}%` : ""}。可以关闭弹窗并继续浏览。`
                  : exportJob.status === "succeeded"
                    ? "产物保存在应用存储中，不会写入原始数据目录。"
                    : "可在任务中心查看错误、重试或取消状态。"}
              </div>
            </div>
          ) : null}
          {compatibilityNotice ? (
            <div aria-live="polite" className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">
              {compatibilityNotice}
            </div>
          ) : null}
        </section>

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleDownload()}
            disabled={((!precheck || precheck.blocked) && exportJob?.status !== "succeeded")
              || downloading
              || checking
              || downloadCompleted
              || exportJobActive}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {downloading ? <LoaderCircle size={17} className="animate-spin" /> : <Download size={17} />}
            {downloadCompleted
              ? "已下载"
              : downloading
                ? "处理中"
                : !usesExportJob(format)
                  ? "确认并下载"
                  : exportJob?.status === "succeeded"
                    ? "下载导出产物"
                    : exportJobFailed
                      ? "重新提交任务"
                      : "提交导出任务"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
