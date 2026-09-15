import axios from "axios";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FolderInput,
  LoaderCircle,
  Search,
  WandSparkles
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  createTriageDirectoryMappingJob,
  createTriageDirectoryMappingPreview,
  getJob,
  getTriageDirectoryMappingPreview,
  getTriageDirectorySources
} from "../api/client";
import type { Job } from "../types/job";
import type {
  DirectoryMappingExistingBehavior,
  DirectoryMappingStatus,
  TriageDirectoryMappingPreviewItem,
  TriageDirectoryMappingPreviewResponse,
  TriageDirectoryMappingRule,
  TriageDirectorySource,
  TriageDirectorySourceResponse
} from "../types/triageDirectoryMapping";
import type { DefectSeverity, OkGrade } from "../types/triage";
import Modal from "./Modal";


interface TriageDirectoryMappingModalProps {
  datasetId: number;
  open: boolean;
  onClose: () => void;
  onCompleted: () => void;
}

const DECISION_LABELS: Record<string, string> = {
  apply: "将写入",
  unchanged: "已经一致",
  skipped_existing: "保留已有判定",
  unmapped: "目录未映射",
  file_unavailable: "文件不可用"
};

const STATUS_LABELS: Record<string, string> = {
  untriaged: "未分拣",
  pending: "待定",
  ok: "OK",
  ng: "NG"
};

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  }
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function directoryLabel(value: string): string {
  return value || "（数据集根目录）";
}

function mappingTargetLabel(
  item: TriageDirectoryMappingPreviewItem,
  sources: TriageDirectorySourceResponse | null
): string {
  if (!item.target_status) return "—";
  const values = [STATUS_LABELS[item.target_status] ?? item.target_status];
  if (item.target_ok_grade) values.push(item.target_ok_grade === "clear" ? "完全 OK" : "勉强 OK");
  if (item.target_defect_type_id) {
    const defect = sources?.defect_types.find((candidate) => candidate.id === item.target_defect_type_id);
    values.push(defect?.name ?? `缺陷 #${item.target_defect_type_id}`);
  }
  if (item.target_defect_severity) {
    values.push({ mild: "轻微", moderate: "中等", severe: "严重" }[item.target_defect_severity]);
  }
  return values.join(" · ");
}

function suggestedRule(
  source: TriageDirectorySource,
  data: TriageDirectorySourceResponse
): TriageDirectoryMappingRule | null {
  const parts = source.directory.split("/").map((part) => part.trim().toLowerCase());
  const joined = parts.join("/");
  const has = (values: string[]) => values.some((value) => parts.includes(value) || joined.includes(value));
  if (has(["pending", "review", "待定", "复核"])) {
    return { source_directory: source.directory, triage_status: "pending" };
  }
  if (has(["ng", "bad", "fail", "defect", "anomaly", "不良", "缺陷", "异常"])) {
    const defect = data.defect_types.find((item) => {
      const name = item.name.toLowerCase();
      const code = item.code.toLowerCase();
      return parts.includes(name) || parts.includes(code);
    });
    let severity: DefectSeverity | undefined;
    if (has(["mild", "minor", "轻微"])) severity = "mild";
    if (has(["moderate", "medium", "中等"])) severity = "moderate";
    if (has(["severe", "major", "critical", "严重"])) severity = "severe";
    return {
      source_directory: source.directory,
      triage_status: "ng",
      defect_type_id: data.triage_policy.ng_grouping.includes("defect_type") ? defect?.id : undefined,
      defect_severity: data.triage_policy.ng_grouping.includes("severity") ? severity : undefined
    };
  }
  if (has(["ok", "good", "pass", "normal", "合格", "良品", "正常"])) {
    let grade: OkGrade | undefined;
    if (has(["borderline", "acceptable", "勉强", "可接受"])) grade = "borderline";
    if (has(["clear", "perfect", "完全ok", "完全合格"])) grade = "clear";
    return {
      source_directory: source.directory,
      triage_status: "ok",
      ok_grade: data.triage_policy.split_ok ? grade : undefined
    };
  }
  return null;
}

export default function TriageDirectoryMappingModal({
  datasetId,
  open,
  onClose,
  onCompleted
}: TriageDirectoryMappingModalProps) {
  const [sources, setSources] = useState<TriageDirectorySourceResponse | null>(null);
  const [mappings, setMappings] = useState<Record<string, TriageDirectoryMappingRule>>({});
  const [existingBehavior, setExistingBehavior] = useState<DirectoryMappingExistingBehavior>("skip");
  const [searchDraft, setSearchDraft] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [loadingSources, setLoadingSources] = useState(false);
  const [checking, setChecking] = useState(false);
  const [paging, setPaging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [preview, setPreview] = useState<TriageDirectoryMappingPreviewResponse | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const requestKey = useMemo(
    () => JSON.stringify({ mappings: Object.values(mappings), existingBehavior }),
    [existingBehavior, mappings]
  );

  useEffect(() => {
    if (!open) return;
    setMappings({});
    setExistingBehavior("skip");
    setSearchDraft("");
    setActiveSearch("");
    setPreview(null);
    setJob(null);
    setError(null);
    void loadSources(1, "");
  }, [datasetId, open]);

  useEffect(() => {
    setPreview(null);
    setJob(null);
  }, [requestKey]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let disposed = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const current = await getJob(job.id);
        if (disposed) return;
        setJob(current);
        if (current.status === "succeeded") onCompleted();
        if (["queued", "running"].includes(current.status)) {
          timer = window.setTimeout(() => void poll(), 750);
        }
      } catch (caught) {
        if (!disposed) setError(errorMessage(caught));
      }
    };
    void poll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [job?.id, job?.status, onCompleted]);

  async function loadSources(page: number, search: string) {
    setLoadingSources(true);
    setError(null);
    try {
      setSources(await getTriageDirectorySources(datasetId, search, page, 50));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoadingSources(false);
    }
  }

  function updateStatus(directory: string, status: "ignore" | DirectoryMappingStatus) {
    setMappings((current) => {
      const next = { ...current };
      if (status === "ignore") {
        delete next[directory];
      } else {
        next[directory] = { source_directory: directory, triage_status: status };
      }
      return next;
    });
  }

  function updateRule(directory: string, updates: Partial<TriageDirectoryMappingRule>) {
    setMappings((current) => ({
      ...current,
      [directory]: { ...current[directory], ...updates }
    }));
  }

  function generateDrafts() {
    if (!sources) return;
    setMappings((current) => {
      const next = { ...current };
      for (const source of sources.items) {
        const suggestion = suggestedRule(source, sources);
        if (suggestion) next[source.directory] = suggestion;
      }
      return next;
    });
  }

  async function runPreview() {
    const rules = Object.values(mappings);
    if (rules.length === 0) {
      setError("请至少映射一个来源目录。未映射目录不会被修改。");
      return;
    }
    setChecking(true);
    setError(null);
    try {
      setPreview(await createTriageDirectoryMappingPreview(datasetId, {
        mappings: rules,
        existing_behavior: existingBehavior
      }));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setChecking(false);
    }
  }

  async function changePreviewPage(page: number) {
    if (!preview) return;
    setPaging(true);
    try {
      setPreview(await getTriageDirectoryMappingPreview(datasetId, preview.plan_id, page, preview.page_size));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPaging(false);
    }
  }

  async function submitJob() {
    if (!preview || preview.blocked) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createTriageDirectoryMappingJob(datasetId, preview.plan_id, preview.plan_hash);
      setJob(result.job);
      window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  const policy = sources?.triage_policy;
  const allowsType = policy?.ng_grouping === "defect_type" || policy?.ng_grouping === "defect_type_and_severity";
  const allowsSeverity = policy?.ng_grouping === "severity" || policy?.ng_grouping === "defect_type_and_severity";
  const jobActive = job?.status === "queued" || job?.status === "running";
  const jobFailed = job?.status === "failed" || job?.status === "cancelled" || job?.status === "interrupted";

  return (
    <Modal open={open} title="从旧目录导入分拣结果" onClose={onClose}>
      <div className="max-h-[86vh] space-y-5 overflow-y-auto px-5 py-5">
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-900">
          系统只读取已扫描图片的相对目录，不移动或重命名文件。每个直接父目录单独映射；未映射目录保持原样。
        </div>

        <section className="space-y-3" aria-labelledby="mapping-source-heading">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="mapping-source-heading" className="text-sm font-semibold text-ink">1. 映射来源目录</h3>
              <p className="mt-1 text-xs text-gray-500">常见名称只能生成草稿，正式写入前仍需预览确认。</p>
            </div>
            <button type="button" onClick={generateDrafts} disabled={!sources?.items.length} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium disabled:opacity-40">
              <WandSparkles size={16} /> 按文件夹名生成草稿
            </button>
          </div>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-3 text-gray-400" />
              <input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { setActiveSearch(searchDraft.trim()); void loadSources(1, searchDraft.trim()); } }} placeholder="搜索目录" className="min-h-10 w-full rounded-lg border border-line pl-9 pr-3 text-sm" />
            </div>
            <button type="button" onClick={() => { const value = searchDraft.trim(); setActiveSearch(value); void loadSources(1, value); }} className="min-h-10 rounded-lg border border-line bg-white px-4 text-sm font-medium">搜索</button>
          </div>

          {loadingSources && <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-4 text-sm text-gray-500"><LoaderCircle size={17} className="animate-spin" />正在读取目录</div>}
          {sources && !loadingSources && (
            <div className="overflow-hidden rounded-xl border border-line">
              <div className="bg-gray-50 px-3 py-2 text-xs text-gray-600">共 {sources.total_directories} 个目录、{sources.total_images} 张图片；已配置 {Object.keys(mappings).length} 个目录</div>
              <div className="max-h-[32vh] divide-y divide-line overflow-auto">
                {sources.items.map((source) => {
                  const rule = mappings[source.directory];
                  return (
                    <div key={source.directory || "__root__"} className="space-y-2 px-3 py-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate font-mono text-sm font-semibold" title={directoryLabel(source.directory)}>{directoryLabel(source.directory)}</div>
                          <div className="mt-1 text-xs text-gray-500">{source.image_count} 张 · 未分拣 {source.untriaged_count} · 已有判定 {source.existing_count}</div>
                          <div className="mt-1 truncate text-xs text-gray-400" title={source.examples.join("、")}>{source.examples.join("、")}</div>
                        </div>
                        <select aria-label={`${directoryLabel(source.directory)} 映射结果`} value={rule?.triage_status ?? "ignore"} onChange={(event) => updateStatus(source.directory, event.target.value as "ignore" | DirectoryMappingStatus)} className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm">
                          <option value="ignore">不导入</option><option value="ok">OK</option><option value="ng">NG</option><option value="pending">待定</option>
                        </select>
                      </div>
                      {rule?.triage_status === "ok" && policy?.split_ok && (
                        <select aria-label={`${directoryLabel(source.directory)} OK 等级`} value={rule.ok_grade ?? ""} onChange={(event) => updateRule(source.directory, { ok_grade: (event.target.value || undefined) as OkGrade | undefined })} className="min-h-10 w-full rounded-lg border border-amber-300 bg-amber-50 px-3 text-sm">
                          <option value="">必须明确选择 OK 等级</option><option value="clear">完全 OK</option><option value="borderline">勉强 OK</option>
                        </select>
                      )}
                      {rule?.triage_status === "ng" && (allowsType || allowsSeverity) && (
                        <div className="grid gap-2 sm:grid-cols-2">
                          {allowsType && <select aria-label={`${directoryLabel(source.directory)} 缺陷类型`} value={rule.defect_type_id ?? ""} onChange={(event) => updateRule(source.directory, { defect_type_id: event.target.value ? Number(event.target.value) : undefined })} className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm"><option value="">缺陷类型未指定</option>{sources.defect_types.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
                          {allowsSeverity && <select aria-label={`${directoryLabel(source.directory)} 缺陷程度`} value={rule.defect_severity ?? ""} onChange={(event) => updateRule(source.directory, { defect_severity: (event.target.value || undefined) as DefectSeverity | undefined })} className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm"><option value="">程度未评估</option><option value="mild">轻微</option><option value="moderate">中等</option><option value="severe">严重</option></select>}
                        </div>
                      )}
                    </div>
                  );
                })}
                {sources.items.length === 0 && <div className="px-3 py-8 text-center text-sm text-gray-500">没有匹配的图片目录</div>}
              </div>
              {sources.page_count > 1 && <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-gray-600"><button type="button" disabled={sources.page <= 1 || loadingSources} onClick={() => void loadSources(sources.page - 1, activeSearch)} className="inline-flex items-center gap-1 disabled:opacity-30"><ChevronLeft size={15} />上一页</button><span>{sources.page} / {sources.page_count}</span><button type="button" disabled={sources.page >= sources.page_count || loadingSources} onClick={() => void loadSources(sources.page + 1, activeSearch)} className="inline-flex items-center gap-1 disabled:opacity-30">下一页<ChevronRight size={15} /></button></div>}
            </div>
          )}
        </section>

        <section className="space-y-3" aria-labelledby="mapping-policy-heading">
          <div>
            <h3 id="mapping-policy-heading" className="text-sm font-semibold text-ink">2. 选择已有判定处理方式</h3>
            <p className="mt-1 text-xs text-gray-500">无论哪种方式，预览后发生变化都会使计划失效。</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className={`cursor-pointer rounded-xl border p-3 ${existingBehavior === "skip" ? "border-gray-900 bg-gray-50" : "border-line"}`}><input type="radio" name="directory-mapping-existing" checked={existingBehavior === "skip"} onChange={() => setExistingBehavior("skip")} /><span className="ml-2 text-sm font-semibold">只填未分拣（推荐）</span><span className="mt-1 block pl-6 text-xs text-gray-500">人工已有结果保持不变</span></label>
            <label className={`cursor-pointer rounded-xl border p-3 ${existingBehavior === "overwrite" ? "border-amber-500 bg-amber-50" : "border-line"}`}><input type="radio" name="directory-mapping-existing" checked={existingBehavior === "overwrite"} onChange={() => setExistingBehavior("overwrite")} /><span className="ml-2 text-sm font-semibold">覆盖已有判定</span><span className="mt-1 block pl-6 text-xs text-amber-800">仅用于确认旧目录更可信的迁移</span></label>
          </div>
          <button type="button" onClick={() => void runPreview()} disabled={checking || loadingSources} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold disabled:opacity-40">{checking ? <LoaderCircle size={17} className="animate-spin" /> : <FolderInput size={17} />}{checking ? "预览中" : "预览将写入的结果"}</button>
        </section>

        {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        {preview && (
          <section className="space-y-3" aria-labelledby="mapping-preview-heading">
            <h3 id="mapping-preview-heading" className="text-sm font-semibold text-ink">3. 确认并导入</h3>
            <div className={`rounded-xl border p-4 ${preview.blocked ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50"}`}>
              <div className="flex items-start gap-2">{preview.blocked ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} className="text-emerald-700" />}<div><div className="text-sm font-semibold">{preview.blocked ? "没有需要写入的变化" : `将更新 ${preview.change_count} 张图片`}</div><div className="mt-1 text-xs text-gray-600">映射命中 {preview.mapped_sample_count} · 已一致 {preview.unchanged_count} · 保留已有 {preview.skipped_existing_count} · 未映射 {preview.unmapped_count} · 不可用 {preview.unavailable_count}</div></div></div>
            </div>
            <div className="overflow-hidden rounded-xl border border-line">
              <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,.8fr)_minmax(0,.9fr)] bg-gray-50 px-3 py-2 text-xs font-medium text-gray-600"><span>图片 / 来源目录</span><span>目标</span><span>处理</span></div>
              <div className="max-h-48 divide-y divide-line overflow-auto">{preview.items.map((item) => <div key={item.sample_id} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,.8fr)_minmax(0,.9fr)] gap-2 px-3 py-2 text-xs"><span className="min-w-0"><span className="block truncate" title={item.relative_path}>{item.relative_path}</span><span className="block truncate text-gray-400">{directoryLabel(item.source_directory)}</span></span><span>{mappingTargetLabel(item, sources)}</span><span className={item.decision === "apply" ? "font-semibold text-emerald-700" : "text-gray-500"}>{DECISION_LABELS[item.decision]}</span></div>)}</div>
              {preview.page_count > 1 && <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-gray-600"><button type="button" disabled={preview.page <= 1 || paging} onClick={() => void changePreviewPage(preview.page - 1)} className="inline-flex items-center gap-1 disabled:opacity-30"><ChevronLeft size={15} />上一页</button><span>{preview.page} / {preview.page_count}</span><button type="button" disabled={preview.page >= preview.page_count || paging} onClick={() => void changePreviewPage(preview.page + 1)} className="inline-flex items-center gap-1 disabled:opacity-30">下一页<ChevronRight size={15} /></button></div>}
            </div>
          </section>
        )}

        {job && <div aria-live="polite" className={`rounded-xl border p-4 ${job.status === "succeeded" ? "border-emerald-200 bg-emerald-50" : jobFailed ? "border-red-200 bg-red-50" : "border-blue-200 bg-blue-50"}`}><div className="text-sm font-semibold">{job.status === "succeeded" ? "旧目录判定已导入" : jobFailed ? "导入未完成" : "后台正在校验并写入"}</div><div className="mt-1 text-xs text-gray-600">{job.stage === "validating_mapping" ? "核对预览后的变化" : job.stage === "applying_mapping" ? "原子写入分拣结果" : job.stage === "completed" ? "已完成" : job.stage}</div>{job.error && typeof job.error.message === "string" && <div className="mt-2 text-xs text-red-700">{job.error.message}</div>}</div>}

        <div className="flex justify-end gap-2 border-t border-line pt-4"><button type="button" onClick={onClose} className="min-h-10 rounded-lg border border-line px-4 text-sm font-medium">关闭</button><button type="button" onClick={() => void submitJob()} disabled={!preview || preview.blocked || checking || submitting || jobActive || job?.status === "succeeded"} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white disabled:bg-gray-300">{submitting || jobActive ? <LoaderCircle size={17} className="animate-spin" /> : <FolderInput size={17} />}{job?.status === "succeeded" ? "导入完成" : jobFailed ? "重新提交" : jobActive ? "导入中" : "确认导入"}</button></div>
      </div>
    </Modal>
  );
}
