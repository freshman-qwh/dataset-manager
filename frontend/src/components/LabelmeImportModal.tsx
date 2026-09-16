import axios from "axios";
import { FormEvent, useEffect, useRef, useState } from "react";

import { createAnnotationImportJob, getJob, importAnnotations } from "../api/client";
import type {
  AnnotationImportFormat,
  AnnotationImportIssue,
  AnnotationImportMode,
  AnnotationImportResult,
  AnnotationImportStrategy
} from "../types/dataset";
import type { Job } from "../types/job";
import Modal from "./Modal";

interface LabelmeImportModalProps {
  datasetId: number;
  open: boolean;
  onClose: () => void;
  onImported: () => Promise<void>;
}

export default function AnnotationImportModal({ datasetId, open, onClose, onImported }: LabelmeImportModalProps) {
  const [format, setFormat] = useState<AnnotationImportFormat>("labelme");
  const [path, setPath] = useState("");
  const [mode, setMode] = useState<AnnotationImportMode>("file");
  const [sampleId, setSampleId] = useState("");
  const [strategy, setStrategy] = useState<AnnotationImportStrategy>("replace");
  const [syncSampleTags, setSyncSampleTags] = useState(false);
  const [preview, setPreview] = useState<AnnotationImportResult | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compatibilityNotice, setCompatibilityNotice] = useState<string | null>(null);
  const refreshedJobIds = useRef(new Set<number>());

  useEffect(() => {
    setPreview(null);
    setJob(null);
    setBusy(false);
    setError(null);
    setCompatibilityNotice(null);
  }, [datasetId]);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      void getJob(job.id).then(async (nextJob) => {
        if (stopped) return;
        setJob(nextJob);
        if (nextJob.status === "succeeded" && !refreshedJobIds.current.has(nextJob.id)) {
          refreshedJobIds.current.add(nextJob.id);
          await onImported();
        }
      }).catch(() => {
        if (!stopped) setError("暂时无法刷新导入任务状态，请在任务中心查看。");
      });
    }, 1000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job, onImported]);

  function invalidatePreview() {
    setPreview(null);
    setJob(null);
    setError(null);
    setCompatibilityNotice(null);
  }

  function requestBase() {
    const parsedSampleId = mode === "file" && sampleId.trim() ? Number(sampleId) : undefined;
    return {
      format,
      path: path.trim(),
      mode,
      sample_id: Number.isInteger(parsedSampleId) && (parsedSampleId ?? 0) > 0 ? parsedSampleId : undefined,
      strategy,
      sync_sample_tags: syncSampleTags
    };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!path.trim()) return;
    setBusy(true);
    setError(null);
    try {
      if (!preview) {
        const result = await importAnnotations(datasetId, { ...requestBase(), dry_run: true });
        setPreview(result);
        return;
      }
      try {
        const created = await createAnnotationImportJob(datasetId, {
          ...requestBase(),
          expected_source_sha256: preview.source_sha256,
          expected_plan_fingerprint: preview.plan_fingerprint
        });
        setJob(created.job);
        window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
      } catch (caught) {
        if (!isJobsSchemaUnavailable(caught)) throw caught;
        const result = await importAnnotations(datasetId, {
          ...requestBase(),
          dry_run: false,
          expected_source_sha256: preview.source_sha256,
          expected_plan_fingerprint: preview.plan_fingerprint
        });
        setPreview(result);
        setCompatibilityNotice("当前数据库尚未启用本地任务，已使用兼容模式完成导入；升级后可使用取消、重试和回滚。");
        await onImported();
      }
    } catch (caught) {
      if (preview && !job) setPreview(null);
      setError(apiErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const locked = Boolean(job);
  const canImport = Boolean(preview && preview.imported_samples > 0);

  return (
    <Modal open={open} title="导入标注" onClose={onClose}>
      <form onSubmit={handleSubmit} className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm leading-6 text-blue-900">
          先执行只读预检，再创建可取消、可重试、可回滚的本地任务。系统只读取标注文件和原图尺寸，不会修改原图或在数据集目录写入旁路文件。
        </div>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">标注格式</span>
          <select
            value={format}
            disabled={locked}
            onChange={(event) => {
              const nextFormat = event.target.value as AnnotationImportFormat;
              setFormat(nextFormat);
              setMode(nextFormat.startsWith("yolo_") ? "directory" : "file");
              setSampleId("");
              invalidatePreview();
            }}
            className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none focus:border-gray-900"
          >
            <option value="labelme">LabelMe JSON</option>
            <option value="yolo_detection">YOLO detection TXT</option>
            <option value="yolo_segmentation">YOLO segmentation TXT</option>
            <option value="coco">COCO JSON</option>
          </select>
          {format.startsWith("yolo_") ? <span className="mt-1 block text-xs text-gray-500">支持 bbox 或 polygon；pose、OBB 暂不支持并会在预检中明确报错。</span> : null}
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">{sourcePathLabel(format, mode)} *</span>
          <input
            value={path}
            disabled={locked}
            onChange={(event) => { setPath(event.target.value); invalidatePreview(); }}
            placeholder={format.startsWith("yolo_") ? "D:/annotations/yolo-dataset" : "D:/annotations/annotations.json"}
            className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
          />
          <span className="mt-1 block text-xs text-gray-500">填写后端可以读取的本机绝对路径，不是浏览器上传。</span>
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          {format === "labelme" ? <label className="block">
            <span className="text-sm font-medium text-gray-700">来源范围</span>
            <select
              value={mode}
              disabled={locked}
              onChange={(event) => { setMode(event.target.value as AnnotationImportMode); invalidatePreview(); }}
              className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none focus:border-gray-900"
            >
              <option value="file">单个 JSON 文件</option>
              <option value="directory">目录内全部 JSON</option>
            </select>
          </label> : <div className="rounded-lg border border-line bg-gray-50 px-3 py-2.5 text-sm text-gray-600">{format === "coco" ? "单个 COCO JSON 文件" : "YOLO 数据集目录（含 labels/ 与 data.yaml 或 classes.txt）"}</div>}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">写入方式</span>
            <select
              value={strategy}
              disabled={locked}
              onChange={(event) => { setStrategy(event.target.value as AnnotationImportStrategy); invalidatePreview(); }}
              className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none focus:border-gray-900"
            >
              <option value="replace">替换匹配样本的标注</option>
              <option value="append">追加到已有标注</option>
            </select>
          </label>
        </div>
        {format === "labelme" && mode === "file" ? (
          <label className="block">
            <span className="text-sm font-medium text-gray-700">指定样本 ID（可选）</span>
            <input
              type="number"
              min={1}
              value={sampleId}
              disabled={locked}
              onChange={(event) => { setSampleId(event.target.value); invalidatePreview(); }}
              placeholder="留空时按 imagePath / 文件名匹配"
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none focus:border-gray-900"
            />
          </label>
        ) : null}
        <label className="flex items-start gap-3 rounded-lg border border-line p-3">
          <input
            type="checkbox"
            checked={syncSampleTags}
            disabled={locked}
            onChange={(event) => { setSyncSampleTags(event.target.checked); invalidatePreview(); }}
            className="mt-1"
          />
          <span>
            <span className="block text-sm font-medium text-gray-700">把对象类别追加为样本标签</span>
            <span className="mt-1 block text-xs leading-5 text-gray-500">仅追加缺失标签，不覆盖已有样本标签；回滚会恢复导入前标签集合。</span>
          </span>
        </label>

        {preview ? <PreviewSummary result={preview} /> : null}
        {job ? <JobStatus job={job} /> : null}
        {compatibilityNotice ? <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">{compatibilityNotice}</div> : null}
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="min-h-11 rounded-lg border border-line px-4 text-sm font-medium text-gray-700 hover:bg-gray-50">关闭</button>
          {!job && !compatibilityNotice ? (
            <button
              type="submit"
              disabled={busy || !path.trim() || Boolean(preview && !canImport)}
              className="min-h-11 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {busy ? "处理中…" : preview ? "确认并创建导入任务" : "执行只读预检"}
            </button>
          ) : null}
        </div>
      </form>
    </Modal>
  );
}

function PreviewSummary({ result }: { result: AnnotationImportResult }) {
  const issues = [...result.errors, ...result.warnings];
  return (
    <section className="rounded-lg border border-line bg-gray-50 p-3" aria-live="polite">
      <div className="text-sm font-semibold text-gray-800">预检结果</div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-sm text-gray-700 sm:grid-cols-4">
        <span>检查 {result.checked_files} 个文件</span>
        <span>匹配 {result.imported_samples} 个样本</span>
        <span>计划 {result.created_annotations} 个对象</span>
        <span>跳过 {result.skipped_shapes} 个 shape</span>
      </div>
      <p className="mt-2 break-all text-xs text-gray-500">源指纹：{result.source_sha256.slice(0, 16)}…</p>
      {issues.length > 0 ? (
        <div className="mt-3 max-h-40 space-y-2 overflow-y-auto">
          {issues.slice(0, 40).map((issue, index) => (
            <IssueRow key={`${issue.code}-${issue.file_path ?? ""}-${index}`} issue={issue} />
          ))}
        </div>
      ) : <p className="mt-3 text-xs text-emerald-700">未发现阻断问题。</p>}
    </section>
  );
}

function IssueRow({ issue }: { issue: AnnotationImportIssue }) {
  return (
    <div className={`rounded-md px-3 py-2 text-xs leading-5 ${issue.severity === "error" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800"}`}>
      <span className="font-medium">{issue.code}</span> · {issue.message}
      {issue.sample_path ? <span className="block truncate opacity-80">{issue.sample_path}</span> : null}
      {issue.file_path ? <span className="block truncate opacity-70">{issue.file_path}</span> : null}
    </div>
  );
}

function JobStatus({ job }: { job: Job }) {
  const progress = job.progress_total && job.progress_total > 0
    ? Math.min(100, Math.round((job.progress_current / job.progress_total) * 100))
    : 0;
  const statusText: Record<Job["status"], string> = {
    queued: "任务等待中",
    running: "正在导入",
    succeeded: "导入完成",
    failed: "导入失败",
    cancelled: "导入已取消",
    interrupted: "导入已中断"
  };
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900" aria-live="polite">
      <div className="flex items-center justify-between gap-3 font-medium"><span>{statusText[job.status]}</span><span>{progress}%</span></div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-blue-100"><div className="h-full rounded-full bg-blue-600 transition-[width]" style={{ width: `${progress}%` }} /></div>
      <p className="mt-2 text-xs leading-5 text-blue-700">任务 #{job.id} 已进入本地任务中心。关闭窗口不会中止任务；可在任务中心取消、重试或回滚已提交变更。</p>
    </div>
  );
}

function apiErrorMessage(caught: unknown): string {
  if (axios.isAxiosError(caught)) {
    const detail = caught.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "标注导入失败，请检查路径、格式、类别定义和样本匹配关系。";
}

function sourcePathLabel(format: AnnotationImportFormat, mode: AnnotationImportMode): string {
  if (format === "coco") return "COCO JSON 文件路径";
  if (format.startsWith("yolo_")) return "YOLO 数据集目录路径";
  return mode === "directory" ? "LabelMe JSON 目录路径" : "LabelMe JSON 文件路径";
}

function isJobsSchemaUnavailable(caught: unknown): boolean {
  if (!axios.isAxiosError(caught) || caught.response?.status !== 409) return false;
  const detail = caught.response?.data?.detail;
  return typeof detail === "string" && detail.toLowerCase().includes("jobs schema");
}
