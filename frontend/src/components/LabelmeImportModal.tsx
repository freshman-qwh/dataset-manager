import axios from "axios";
import { Check, CircleHelp } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { createAnnotationImportJob, getJob, importAnnotations } from "../api/client";
import type {
  AnnotationImportFormat,
  AnnotationImportIssue,
  AnnotationImportMode,
  AnnotationImportResult,
  AnnotationImportStrategy,
  Sample
} from "../types/dataset";
import type { Job } from "../types/job";
import Modal from "./Modal";
import DirectoryPickerModal from "./DirectoryPickerModal";
import ImportSamplePickerModal, { ImportSampleThumbnail } from "./ImportSamplePickerModal";

interface LabelmeImportModalProps {
  datasetId: number;
  datasetRoot: string;
  datasetCreatedAt: string;
  open: boolean;
  onClose: () => void;
  onImported: () => Promise<void>;
}

export default function AnnotationImportModal({ datasetId, datasetRoot, datasetCreatedAt, open, onClose, onImported }: LabelmeImportModalProps) {
  const [format, setFormat] = useState<AnnotationImportFormat>("labelme");
  const [path, setPath] = useState("");
  const [mode, setMode] = useState<AnnotationImportMode>("file");
  const [selectedSample, setSelectedSample] = useState<Sample | null>(null);
  const [pathPickerOpen, setPathPickerOpen] = useState(false);
  const [samplePickerOpen, setSamplePickerOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [strategy, setStrategy] = useState<AnnotationImportStrategy>("replace");
  const [syncSampleTags, setSyncSampleTags] = useState(false);
  const [preview, setPreview] = useState<AnnotationImportResult | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compatibilityNotice, setCompatibilityNotice] = useState<string | null>(null);
  const refreshedJobIds = useRef(new Set<number>());
  const requestGeneration = useRef(0);
  const datasetKey = `${datasetId}:${datasetCreatedAt}:${datasetRoot}`;

  function storedPath(nextFormat: AnnotationImportFormat, nextMode: AnnotationImportMode) {
    try { return localStorage.getItem(`annotation-import-path:${datasetKey}:${nextFormat}:${nextMode}`) || ""; }
    catch { return ""; }
  }

  function rememberPath() {
    try { localStorage.setItem(`annotation-import-path:${datasetKey}:${format}:${mode}`, path.trim()); }
    catch { /* Path history is optional when browser storage is unavailable. */ }
  }

  function changeSource(nextFormat: AnnotationImportFormat, nextMode: AnnotationImportMode) {
    setFormat(nextFormat);
    setMode(nextMode);
    setPath(storedPath(nextFormat, nextMode) || (nextMode === "directory" ? datasetRoot : ""));
    setSelectedSample(null);
    invalidatePreview();
  }

  useEffect(() => {
    requestGeneration.current += 1;
    if (!open) return;
    setFormat("labelme");
    setMode("file");
    setPath(storedPath("labelme", "file"));
    setSelectedSample(null);
    setPathPickerOpen(false);
    setSamplePickerOpen(false);
    setHelpOpen(false);
    setStrategy("replace");
    setSyncSampleTags(false);
    setPreview(null);
    setJob(null);
    setBusy(false);
    setError(null);
    setCompatibilityNotice(null);
  }, [open, datasetKey]);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      void getJob(job.id).then(async (nextJob) => {
        if (stopped) return;
        setJob(nextJob);
      }).catch(() => {
        if (!stopped) setError("暂时无法刷新导入任务状态，请在任务中心查看。");
      });
    }, 1000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job, onImported]);

  useEffect(() => {
    if (job?.status !== "succeeded") return;
    rememberPath();
    if (refreshedJobIds.current.has(job.id)) return;
    refreshedJobIds.current.add(job.id);
    void onImported().catch(() => setError("导入已完成，暂时无法刷新数据集，请刷新页面查看。"));
  }, [job, onImported]);

  function invalidatePreview() {
    requestGeneration.current += 1;
    setPreview(null);
    setJob(null);
    setError(null);
    setCompatibilityNotice(null);
  }

  function requestBase() {
    return {
      format,
      path: path.trim(),
      mode,
      sample_id: format === "labelme" && mode === "file" ? selectedSample?.id : undefined,
      strategy,
      sync_sample_tags: syncSampleTags
    };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!path.trim()) return;
    setBusy(true);
    setError(null);
    const generation = requestGeneration.current;
    try {
      if (!preview) {
        const result = await importAnnotations(datasetId, { ...requestBase(), dry_run: true });
        if (generation !== requestGeneration.current) return;
        setPreview(result);
        return;
      }
      try {
        const created = await createAnnotationImportJob(datasetId, {
          ...requestBase(),
          expected_source_sha256: preview.source_sha256,
          expected_plan_fingerprint: preview.plan_fingerprint
        });
        if (generation !== requestGeneration.current) return;
        setJob(created.job);
        window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
      } catch (caught) {
        if (generation !== requestGeneration.current) return;
        if (!isJobsSchemaUnavailable(caught)) throw caught;
        const result = await importAnnotations(datasetId, {
          ...requestBase(),
          dry_run: false,
          expected_source_sha256: preview.source_sha256,
          expected_plan_fingerprint: preview.plan_fingerprint
        });
        if (generation !== requestGeneration.current) return;
        setPreview(result);
        setCompatibilityNotice("当前数据库尚未启用本地任务，已使用兼容模式完成导入；升级后可使用取消、重试和回滚。");
        rememberPath();
        await onImported();
      }
    } catch (caught) {
      if (generation !== requestGeneration.current) return;
      if (preview && !job) setPreview(null);
      setError(apiErrorMessage(caught));
    } finally {
      if (generation === requestGeneration.current) setBusy(false);
    }
  }

  const locked = busy || Boolean(job);
  const canImport = Boolean(preview && preview.imported_samples > 0);

  return (
    <>
    <Modal open={open && !pathPickerOpen && !samplePickerOpen} title="导入标注" onClose={onClose} dismissible={!busy}>
      <form onSubmit={handleSubmit} className="max-h-[78vh] space-y-3 overflow-y-auto px-5 py-4">
        <ol aria-label="导入步骤" className="flex items-center gap-2 text-xs text-gray-500">
          {["选择来源", "检查匹配", "导入"].map((label, index) => {
            const step = job || compatibilityNotice ? 2 : preview ? 1 : 0;
            return <li key={label} aria-current={index === step ? "step" : undefined} className={`flex flex-1 items-center gap-2 ${index === step ? "font-semibold text-gray-900" : ""}`}>
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${index <= step ? "bg-gray-900 text-white" : "bg-gray-100"}`}>{index < step || (index === 2 && (job?.status === "succeeded" || compatibilityNotice)) ? <Check size={14} /> : index + 1}</span>{label}
            </li>;
          })}
        </ol>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>只更新系统内的标注，不修改原始文件。</span>
          <span className="group relative">
            <button type="button" aria-label="导入流程说明" aria-describedby="annotation-import-help" aria-expanded={helpOpen} onClick={() => setHelpOpen(!helpOpen)} className="rounded p-1 hover:bg-gray-100 focus-visible:outline focus-visible:outline-2"><CircleHelp size={15} /></button>
            <span id="annotation-import-help" role="tooltip" className={`${helpOpen ? "block" : "hidden group-hover:block group-focus-within:block"} absolute right-0 top-full z-10 w-64 rounded-lg border border-line bg-white p-3 text-xs leading-5 text-gray-600 shadow-soft`}>先检查文件与图片的匹配关系，再确认写入。导入任务可在任务中心查看、取消、重试或回滚；关闭窗口不会中止任务。</span>
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">标注格式</span>
          <select
            aria-label="标注格式"
            value={format}
            disabled={locked}
            onChange={(event) => {
              const nextFormat = event.target.value as AnnotationImportFormat;
              changeSource(nextFormat, nextFormat.startsWith("yolo_") ? "directory" : "file");
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
        {format === "labelme" ? <label className="block">
          <span className="text-sm font-medium text-gray-700">导入范围</span>
          <select value={mode} disabled={locked} onChange={(event) => changeSource(format, event.target.value as AnnotationImportMode)} className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none focus:border-gray-900">
            <option value="file">单个 JSON 文件</option>
            <option value="directory">整个目录（包含子目录）</option>
          </select>
        </label> : <p className="text-xs text-gray-500">{format === "coco" ? "导入范围：单个 COCO JSON 文件" : "导入范围：YOLO 数据集目录（含 labels/ 与 data.yaml 或 classes.txt）"}</p>}
        </div>
        <div>
          <label htmlFor="annotation-import-path" className="text-sm font-medium text-gray-700">{sourcePathLabel(format, mode)} *</label>
          <div className="mt-2 flex gap-2">
          <input
            id="annotation-import-path"
            value={path}
            disabled={locked}
            onChange={(event) => { setPath(event.target.value); setSelectedSample(null); invalidatePreview(); }}
            placeholder={mode === "directory" ? "选择标注所在目录" : "选择 JSON 文件"}
            className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
          />
          <button type="button" disabled={locked} onClick={() => setPathPickerOpen(true)} className="shrink-0 rounded-lg border border-line px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">浏览…</button>
          </div>
          <span className="mt-1 block text-xs text-gray-500">选择本机路径，也可直接粘贴；不会上传文件。</span>
        </div>
        {format === "labelme" && mode === "file" ? <div className="rounded-lg border border-line p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-gray-700">对应图片：{selectedSample ? "手动选择" : "自动匹配"}</span>
            <button type="button" disabled={locked} onClick={() => setSamplePickerOpen(true)} className="rounded px-2 py-1 text-sm text-gray-700 underline disabled:opacity-40">{selectedSample ? "更换图片" : "手动选择图片"}</button>
          </div>
          {selectedSample ? <div className="mt-2 flex items-center gap-3">
            <ImportSampleThumbnail sample={selectedSample} />
            <span className="min-w-0 flex-1 break-all text-xs text-gray-600">{selectedSample.relative_path}</span>
            <button type="button" disabled={locked} onClick={() => { setSelectedSample(null); invalidatePreview(); }} className="shrink-0 text-xs text-gray-600 underline disabled:opacity-40">恢复自动</button>
          </div> : <p className="mt-1 text-xs text-gray-500">按 JSON 中的图片路径或文件名匹配；无法匹配时可手动选择。</p>}
        </div> : null}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">已有标注处理</span>
            <select
              value={strategy}
              disabled={locked}
              onChange={(event) => { setStrategy(event.target.value as AnnotationImportStrategy); invalidatePreview(); }}
              className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none focus:border-gray-900"
            >
              <option value="replace">替换已有标注</option>
              <option value="append">保留已有标注并追加</option>
            </select>
            <span className="mt-1 block text-xs text-gray-500">{strategy === "replace" ? "将替换本次匹配图片的已有标注；其他图片不受影响。" : "保留原有对象，追加本次导入的对象。"}</span>
          </label>
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
            <span className="mt-1 block text-xs leading-5 text-gray-500">仅追加缺失标签，不覆盖已有标签。</span>
          </span>
        </label>

        {preview ? <PreviewSummary result={preview} /> : null}
        {job ? <JobStatus job={job} /> : null}
        {compatibilityNotice ? <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">{compatibilityNotice}</div> : null}
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" disabled={busy} onClick={onClose} className="min-h-11 rounded-lg border border-line px-4 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">关闭</button>
          {!job && !compatibilityNotice ? (
            <button
              type="submit"
              disabled={busy || !path.trim() || Boolean(preview && !canImport)}
              className="min-h-11 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {busy ? "处理中…" : preview ? "确认导入" : "检查匹配"}
            </button>
          ) : null}
        </div>
      </form>
    </Modal>
    <DirectoryPickerModal open={open && pathPickerOpen} mode={mode} initialPath={path.trim() || storedPath(format, mode) || datasetRoot} onClose={() => setPathPickerOpen(false)} onSelect={(nextPath) => { setPath(nextPath); setSelectedSample(null); invalidatePreview(); }} />
    <ImportSamplePickerModal datasetId={datasetId} open={open && samplePickerOpen} onClose={() => setSamplePickerOpen(false)} onSelect={(sample) => { setSelectedSample(sample); invalidatePreview(); }} />
    </>
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
      {result.matched_sample ? <p className="mt-2 break-all text-sm text-gray-700">对应图片：{result.matched_sample.relative_path}</p> : null}
      <details className="mt-2 text-xs text-gray-500"><summary className="cursor-pointer">技术详情</summary><p className="mt-1 break-all">源指纹：{result.source_sha256}</p></details>
      {issues.length > 0 ? (
        <div className="mt-3 max-h-40 space-y-2 overflow-y-auto">
          {issues.slice(0, 40).map((issue, index) => (
            <IssueRow key={`${issue.code}-${issue.file_path ?? ""}-${index}`} issue={issue} />
          ))}
        </div>
      ) : <p className="mt-3 text-xs text-gray-600">{result.imported_samples > 0 ? "检查通过，可确认导入。" : "没有可导入的图片，请检查来源。"}</p>}
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
