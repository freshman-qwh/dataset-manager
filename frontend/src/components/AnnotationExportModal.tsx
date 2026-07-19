import { AlertTriangle, CheckCircle2, Download, Info, LoaderCircle, SearchCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { downloadAnnotationExport, precheckAnnotationExport } from "../api/client";
import type {
  AnnotationExportFormat,
  AnnotationExportPrecheckResponse,
  AnnotationExportSampleQuery
} from "../types/annotationExport";
import Modal from "./Modal";

type ExportScope = "filtered" | "all" | "split" | "selected";

interface AnnotationExportModalProps {
  datasetId: number;
  open: boolean;
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

export default function AnnotationExportModal({
  datasetId,
  open,
  currentQuery,
  selectedSampleIds,
  onClose
}: AnnotationExportModalProps) {
  const [format, setFormat] = useState<AnnotationExportFormat>("labelme");
  const [scope, setScope] = useState<ExportScope>("filtered");
  const [selectedSplit, setSelectedSplit] = useState("train");
  const [includeEmpty, setIncludeEmpty] = useState(false);
  const [precheck, setPrecheck] = useState<AnnotationExportPrecheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
  }, [format, includeEmpty, sampleQuery]);

  useEffect(() => {
    if (!open) {
      setChecking(false);
      setDownloading(false);
    }
  }, [open]);

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
    } catch {
      setError("预检失败，请确认后端服务可用。");
    } finally {
      setChecking(false);
    }
  }

  async function handleDownload() {
    if (!precheck || precheck.blocked) {
      return;
    }
    setDownloading(true);
    setError(null);
    try {
      const result = await downloadAnnotationExport(datasetId, format, sampleQuery, includeEmpty);
      triggerDownload(result.blob, result.filename);
      onClose();
    } catch {
      setError("导出失败。数据可能在预检后发生变化，请重新预检。");
      setPrecheck(null);
    } finally {
      setDownloading(false);
    }
  }

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
              包含空标注图片
              <span className="mt-1 block text-xs leading-5 text-gray-500">
                默认跳过没有目标格式兼容对象的图片；启用后会生成空记录或空标签文件。
              </span>
            </span>
          </label>
        </section>

        <section className="space-y-3" aria-labelledby="annotation-export-precheck">
          <div className="flex items-center justify-between gap-3">
            <h3 id="annotation-export-precheck" className="text-sm font-semibold text-ink">
              2. 运行预检
            </h3>
            <button
              type="button"
              onClick={() => void handlePrecheck()}
              disabled={checking || (scope === "selected" && selectedSampleIds.length === 0)}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              {checking ? <LoaderCircle size={16} className="animate-spin" /> : <SearchCheck size={16} />}
              {checking ? "预检中" : "运行预检"}
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
                      {precheck.blocked ? "存在阻断问题，暂不能导出" : "预检通过，可以导出"}
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
            disabled={!precheck || precheck.blocked || downloading || checking}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {downloading ? <LoaderCircle size={17} className="animate-spin" /> : <Download size={17} />}
            {downloading ? "生成中" : "确认并下载"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
