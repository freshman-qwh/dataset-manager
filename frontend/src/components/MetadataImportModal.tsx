import { FormEvent, useEffect, useRef, useState } from "react";
import axios from "axios";

import { createMetadataImportJob, getJob, importMetadata } from "../api/client";
import type { MetadataImportIssue, MetadataImportResult } from "../types/dataset";
import type { Job } from "../types/job";
import Modal from "./Modal";

interface MetadataImportModalProps {
  datasetId: number;
  open: boolean;
  onClose: () => void;
  onImported: () => Promise<void>;
}

export default function MetadataImportModal({ datasetId, open, onClose, onImported }: MetadataImportModalProps) {
  const [filePath, setFilePath] = useState("");
  const [matchBy, setMatchBy] = useState("relative_path");
  const [tagColumn, setTagColumn] = useState("tags");
  const [replaceTags, setReplaceTags] = useState(false);
  const [result, setResult] = useState<MetadataImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [compatibilityNotice, setCompatibilityNotice] = useState<string | null>(null);
  const refreshedJobIds = useRef(new Set<number>());

  useEffect(() => {
    setResult(null);
    setError(null);
    setBusy(false);
    setJob(null);
    setCompatibilityNotice(null);
  }, [datasetId]);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) {
      return;
    }
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
    setResult(null);
    setError(null);
    setJob(null);
    setCompatibilityNotice(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!filePath.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    const preview = result?.dry_run ? result : null;
    if (!preview) {
      setResult(null);
    }
    try {
      if (!preview) {
        const nextResult = await importMetadata(datasetId, {
          file_path: filePath.trim(),
          match_by: matchBy,
          tag_column: tagColumn.trim() || "tags",
          replace_tags: replaceTags,
          dry_run: true
        });
        setResult(nextResult);
      } else {
        try {
          const created = await createMetadataImportJob(datasetId, {
            file_path: filePath.trim(),
            match_by: matchBy,
            tag_column: tagColumn.trim() || "tags",
            replace_tags: replaceTags,
            expected_source_sha256: preview.source_sha256
          });
          setJob(created.job);
          window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
        } catch (caught) {
          if (!isJobsSchemaUnavailable(caught)) throw caught;
          const nextResult = await importMetadata(datasetId, {
            file_path: filePath.trim(),
            match_by: matchBy,
            tag_column: tagColumn.trim() || "tags",
            replace_tags: replaceTags,
            dry_run: false,
            expected_source_sha256: preview.source_sha256
          });
          setResult(nextResult);
          setCompatibilityNotice("当前数据库尚未启用本地任务，已使用兼容模式完成本次导入；升级后可使用取消、重试和回滚。");
          await onImported();
        }
      }
    } catch (caught) {
      if (preview && !job) {
        setResult(null);
      }
      setError(apiErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title="导入元数据" onClose={onClose}>
      <form onSubmit={handleSubmit} className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">CSV / JSON 文件路径 *</span>
          <input
            disabled={Boolean(job)}
            value={filePath}
            onChange={(event) => {
              setFilePath(event.target.value);
              invalidatePreview();
            }}
            className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            placeholder="D:/metadata/sample_labels.csv"
          />
          <span className="mt-1 block text-xs text-gray-500">这里填写后端能读取到的本机绝对路径，不是浏览器上传。</span>
        </label>
        <div className="rounded-lg border border-line bg-gray-50 p-3 text-xs text-gray-600">
          <div className="font-medium text-gray-700">CSV 示例</div>
          <pre className="mt-2 overflow-auto rounded-md bg-white p-2">{`relative_path,tags,split,notes,quality
images/a.png,"cat;review",train,"good sample",high`}</pre>
          <div className="mt-3 font-medium text-gray-700">JSON 示例</div>
          <pre className="mt-2 overflow-auto rounded-md bg-white p-2">{`[
  {
    "relative_path": "images/a.png",
    "tags": ["cat", "review"],
    "split": "train",
    "notes": "good sample",
    "quality": "high"
  }
]`}</pre>
          <div className="mt-2">导入只更新已经扫描登记的样本；如果刚修改扫描目录，请先执行扫描。</div>
          <div className="mt-1">`relative_path` 相对于数据集扫描目录；`absolute_path` 可使用 `D:/...` 或 `D:\...`，系统会归一化后匹配。除匹配字段、tags、split、notes 外，其余字段会写入样本自定义元数据。</div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">匹配字段</span>
            <select
              disabled={Boolean(job)}
              value={matchBy}
              onChange={(event) => {
                setMatchBy(event.target.value);
                invalidatePreview();
              }}
              className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            >
              <option value="relative_path">relative_path</option>
              <option value="filename">filename</option>
              <option value="absolute_path">absolute_path</option>
              <option value="file_hash">file_hash</option>
              <option value="sample_id">sample_id</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">标签列</span>
            <input
              disabled={Boolean(job)}
              value={tagColumn}
              onChange={(event) => {
                setTagColumn(event.target.value);
                invalidatePreview();
              }}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            disabled={Boolean(job)}
            checked={replaceTags}
            onChange={(event) => {
              setReplaceTags(event.target.checked);
              invalidatePreview();
            }}
          />
          替换已有标签
        </label>
        {result && (
          <div className="rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-700">
            <div className="mb-2 font-medium text-gray-900">{result.dry_run ? "预检结果（尚未写入）" : "导入结果"}</div>
            <div>总行数：{result.total_rows}</div>
            <div>匹配：{result.matched}</div>
            <div>预计更新：{result.planned_updates}</div>
            {!result.dry_run && <div>已更新：{result.updated}</div>}
            <div>跳过：{result.skipped}</div>
            <div>错误：{result.error_count}</div>
            {result.issues.length > 0 && (
              <div className="mt-2 max-h-28 overflow-auto rounded-md bg-white p-2 text-xs text-red-700">
                {result.issues.map((item, index) => (
                  <div key={`${item.code}:${item.row_number ?? "global"}:${index}`}>
                    {item.row_number ? `第 ${item.row_number} 行 · ` : ""}{item.code} · {metadataIssueMessage(item)}
                  </div>
                ))}
              </div>
            )}
            {result.dry_run && result.planned_updates > 0 && (
              <div className="mt-2 text-xs text-gray-500">确认后会创建可取消、可重试的分批任务；文件发生变化将要求重新预检，已提交变更可从任务中心显式回滚。</div>
            )}
          </div>
        )}
        {job && <MetadataImportJobStatus job={job} />}
        {compatibilityNotice && <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">{compatibilityNotice}</div>}
        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            关闭
          </button>
          <button
            type="submit"
            disabled={busy || Boolean(job) || !filePath.trim() || (result?.dry_run === true && result.planned_updates === 0)}
            className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {busy
              ? (result?.dry_run ? "提交任务中" : "预检中")
              : (result?.dry_run ? `确认导入 ${result.planned_updates} 行` : "预览导入")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function MetadataImportJobStatus({ job }: { job: Job }) {
  const progress = job.progress_total && job.progress_total > 0
    ? Math.min(100, Math.round((job.progress_current / job.progress_total) * 100))
    : 0;
  const statusText: Record<Job["status"], string> = {
    queued: "等待开始",
    running: "正在分批写入",
    succeeded: "导入完成",
    failed: "导入失败",
    cancelled: "导入已取消",
    interrupted: "导入已中断"
  };
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
      <div className="flex items-center justify-between gap-3 font-medium">
        <span>{statusText[job.status]}</span>
        <span>{progress}%</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-blue-100">
        <div className="h-full rounded-full bg-blue-600 transition-[width]" style={{ width: `${progress}%` }} />
      </div>
      <p className="mt-2 text-xs leading-5 text-blue-700">任务 #{job.id} 已进入本地任务中心。关闭窗口不会中止任务；可在任务中心取消、重试或回滚已提交变更。</p>
    </div>
  );
}

function metadataIssueMessage(issue: MetadataImportIssue): string {
  const matchValue = issue.match_value ? `（值：${issue.match_value}）` : "";
  const messages: Record<string, string> = {
    AMBIGUOUS_SAMPLE_MATCH: "匹配到多个样本，请改用相对路径或样本 ID",
    INVALID_REVIEW_STATUS: "审核状态值不受支持",
    MISSING_MATCH_VALUE: "缺少匹配字段值",
    NO_SAMPLES: "数据集还没有已扫描登记的样本",
    SAMPLE_NOT_FOUND: "未找到对应样本"
  };
  return `${messages[issue.code] ?? issue.message}${matchValue}`;
}

function apiErrorMessage(caught: unknown): string {
  if (axios.isAxiosError(caught)) {
    const detail = caught.response?.data?.detail;
    if (typeof detail === "string") {
      return detail;
    }
  }
  return "导入失败，请检查文件路径、格式和匹配字段。";
}

function isJobsSchemaUnavailable(caught: unknown): boolean {
  if (!axios.isAxiosError(caught) || caught.response?.status !== 409) return false;
  const detail = caught.response?.data?.detail;
  return typeof detail === "string" && detail.toLowerCase().includes("jobs schema");
}
