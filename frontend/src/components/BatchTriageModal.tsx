import axios from "axios";
import { AlertTriangle, CheckCircle2, Eye, LoaderCircle, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  commitBatchTriage,
  getTriagePolicy,
  listDefectTypes,
  previewBatchTriage
} from "../api/client";
import type {
  BatchDefectTypesMode,
  BatchFieldMode,
  BatchTriageOperation,
  BatchTriagePreviewResponse,
  BatchTriageState,
  DefectSeverity,
  DefectType,
  OkGrade,
  TriagePolicy,
  TriageStatus
} from "../types/triage";
import Modal from "./Modal";

interface BatchTriageModalProps {
  datasetId: number;
  selectedSampleIds: number[];
  open: boolean;
  onClose: () => void;
  onCompleted: () => void;
}

const STATUS_LABELS: Record<TriageStatus, string> = {
  untriaged: "未分拣",
  pending: "待确认",
  ok: "OK",
  ng: "NG"
};

const GRADE_LABELS: Record<OkGrade, string> = {
  clear: "完全 OK",
  borderline: "勉强 OK"
};

const SEVERITY_LABELS: Record<DefectSeverity, string> = {
  mild: "轻微",
  moderate: "中等",
  severe: "严重"
};

function initialOperation(): BatchTriageOperation {
  return {
    triage_status_mode: "preserve",
    triage_status: null,
    ok_grade_mode: "preserve",
    ok_grade: null,
    defect_severity_mode: "preserve",
    defect_severity: null,
    defect_types_mode: "preserve",
    defect_type_ids: [],
    primary_defect_type_mode: "preserve",
    primary_defect_type_id: null,
    triage_note_mode: "preserve",
    triage_note: null
  };
}

function errorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) return fallback;
  const detail = error.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") {
    return detail[0].msg.replace(/^Value error, /, "");
  }
  return fallback;
}

function stateLabel(state: BatchTriageState, defectTypes: Map<number, DefectType>): string {
  const parts = [STATUS_LABELS[state.triage_status]];
  if (state.ok_grade) parts.push(GRADE_LABELS[state.ok_grade]);
  if (state.defect_severity) parts.push(SEVERITY_LABELS[state.defect_severity]);
  if (state.defect_type_ids.length > 0) {
    parts.push(
      state.defect_type_ids
        .map((item) => defectTypes.get(item)?.name ?? `类型 #${item}`)
        .join("、")
    );
  }
  if (state.triage_note) parts.push(`备注：${state.triage_note}`);
  if (state.outdated) parts.push("待复核");
  return parts.join(" · ");
}

function statusChoice(operation: BatchTriageOperation): string {
  if (operation.triage_status_mode === "clear") return "clear";
  if (operation.triage_status_mode === "set") return `set:${operation.triage_status}`;
  return "preserve";
}

function optionalChoice(mode: BatchFieldMode, value: string | null | undefined): string {
  if (mode === "set") return `set:${value}`;
  return mode;
}

export default function BatchTriageModal({
  datasetId,
  selectedSampleIds,
  open,
  onClose,
  onCompleted
}: BatchTriageModalProps) {
  const [policy, setPolicy] = useState<TriagePolicy | null>(null);
  const [defectTypes, setDefectTypes] = useState<DefectType[]>([]);
  const [operation, setOperation] = useState<BatchTriageOperation>(initialOperation);
  const [preview, setPreview] = useState<BatchTriagePreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const selectionKey = selectedSampleIds.join(",");

  const activeDefectTypes = useMemo(
    () => defectTypes.filter((item) => item.is_active),
    [defectTypes]
  );
  const defectTypeMap = useMemo(
    () => new Map(defectTypes.map((item) => [item.id, item])),
    [defectTypes]
  );
  const allowsType = policy?.ng_grouping === "defect_type" || policy?.ng_grouping === "defect_type_and_severity";
  const allowsSeverity = policy?.ng_grouping === "severity" || policy?.ng_grouping === "defect_type_and_severity";
  const resettingJudgment = operation.triage_status_mode === "clear";
  const hasOperation = [
    operation.triage_status_mode,
    operation.ok_grade_mode,
    operation.defect_severity_mode,
    operation.defect_types_mode,
    operation.primary_defect_type_mode,
    operation.triage_note_mode
  ].some((mode) => mode !== "preserve");

  useEffect(() => {
    if (!open) return;
    setOperation(initialOperation());
    setPreview(null);
    setError(null);
    setSuccess(null);
    setLoading(true);
    void Promise.all([getTriagePolicy(datasetId), listDefectTypes(datasetId, true)])
      .then(([nextPolicy, nextTypes]) => {
        setPolicy(nextPolicy);
        setDefectTypes(nextTypes);
      })
      .catch((caught) => setError(errorMessage(caught, "批量分拣配置加载失败。")))
      .finally(() => setLoading(false));
  }, [datasetId, open, selectionKey]);

  function updateOperation(change: Partial<BatchTriageOperation>) {
    setOperation((current) => ({ ...current, ...change }));
    setPreview(null);
    setError(null);
    setSuccess(null);
  }

  function changeStatus(value: string) {
    if (value === "clear") {
      setOperation({ ...initialOperation(), triage_status_mode: "clear" });
      setPreview(null);
      setError(null);
      setSuccess(null);
      return;
    }
    if (value === "preserve") {
      updateOperation({ triage_status_mode: "preserve", triage_status: null });
      return;
    }
    updateOperation({
      triage_status_mode: "set",
      triage_status: value.replace("set:", "") as TriageStatus
    });
  }

  function changeOptionalField(
    field: "ok_grade" | "defect_severity",
    value: string
  ) {
    const modeField = `${field}_mode` as "ok_grade_mode" | "defect_severity_mode";
    if (value === "preserve" || value === "clear") {
      updateOperation({ [modeField]: value, [field]: null });
      return;
    }
    updateOperation({
      [modeField]: "set",
      [field]: value.replace("set:", "")
    });
  }

  function changeDefectTypesMode(mode: BatchDefectTypesMode) {
    updateOperation({
      defect_types_mode: mode,
      defect_type_ids: mode === "append" || mode === "replace" ? operation.defect_type_ids : []
    });
  }

  function toggleDefectType(defectTypeId: number) {
    const next = new Set(operation.defect_type_ids);
    if (next.has(defectTypeId)) next.delete(defectTypeId);
    else next.add(defectTypeId);
    updateOperation({ defect_type_ids: Array.from(next).sort((left, right) => left - right) });
  }

  async function runPreview() {
    if (!hasOperation || selectedSampleIds.length === 0 || selectedSampleIds.length > 200) return;
    setPreviewing(true);
    setError(null);
    setSuccess(null);
    try {
      setPreview(await previewBatchTriage(datasetId, selectedSampleIds, operation));
    } catch (caught) {
      setError(errorMessage(caught, "批量分拣预览失败，请刷新后重试。"));
    } finally {
      setPreviewing(false);
    }
  }

  async function applyPreview() {
    if (!preview?.can_apply) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await commitBatchTriage(datasetId, {
        policy_version: preview.policy_version,
        preview_hash: preview.preview_hash,
        expected_samples: preview.expected_samples,
        operation
      });
      setSuccess(`已更新 ${result.updated} 张图片，${result.unchanged} 张无需变化。`);
      setPreview(null);
      onCompleted();
    } catch (caught) {
      setPreview(null);
      setError(errorMessage(caught, "批量分拣提交失败；本次操作未写入，请重新预览。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} title="批量分拣" onClose={onClose} size="xl">
      <div className="max-h-[86vh] space-y-5 overflow-y-auto px-5 py-5">
        <section className="rounded-xl border border-line bg-gray-50 p-4">
          <div className="text-sm font-semibold text-ink">已选择 {selectedSampleIds.length} 个样本</div>
          <p className="mt-1 text-xs leading-5 text-gray-600">
            一次最多处理 200 张图片。只有预览确认后才会写入；任一图片版本或内容发生变化时，整批拒绝且不部分保存。
          </p>
          {selectedSampleIds.length > 200 && (
            <p className="mt-2 text-xs font-medium text-red-700">请将选择缩减到 200 张以内。</p>
          )}
        </section>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <LoaderCircle size={17} className="animate-spin" />加载分拣层级与缺陷类型…
          </div>
        )}

        {!loading && policy && (
          <section className="space-y-4" aria-labelledby="batch-triage-fields">
            <div>
              <h3 id="batch-triage-fields" className="text-sm font-semibold text-ink">1. 选择要修改的字段</h3>
              <p className="mt-1 text-xs text-gray-500">“保留”不会覆盖原值；“清空”会明确移除该字段。</p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm font-medium text-gray-800">
                判定
                <select value={statusChoice(operation)} onChange={(event) => changeStatus(event.target.value)} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm">
                  <option value="preserve">保留原判定</option>
                  <option value="set:pending">设置为待确认</option>
                  <option value="set:ok">设置为 OK</option>
                  <option value="set:ng">设置为 NG</option>
                  <option value="clear">清空判定及全部分拣详情</option>
                </select>
              </label>

              <label className="space-y-2 text-sm font-medium text-gray-800">
                OK 等级
                <select disabled={resettingJudgment} value={optionalChoice(operation.ok_grade_mode, operation.ok_grade)} onChange={(event) => changeOptionalField("ok_grade", event.target.value)} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm disabled:bg-gray-100">
                  <option value="preserve">保留原等级</option>
                  <option value="clear">清空等级</option>
                  {policy.split_ok && <option value="set:clear">设置为完全 OK</option>}
                  {policy.split_ok && <option value="set:borderline">设置为勉强 OK</option>}
                </select>
              </label>

              <label className="space-y-2 text-sm font-medium text-gray-800">
                缺陷程度
                <select disabled={resettingJudgment} value={optionalChoice(operation.defect_severity_mode, operation.defect_severity)} onChange={(event) => changeOptionalField("defect_severity", event.target.value)} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm disabled:bg-gray-100">
                  <option value="preserve">保留原程度</option>
                  <option value="clear">清空程度</option>
                  {allowsSeverity && <option value="set:mild">设置为轻微</option>}
                  {allowsSeverity && <option value="set:moderate">设置为中等</option>}
                  {allowsSeverity && <option value="set:severe">设置为严重</option>}
                </select>
              </label>

              <label className="space-y-2 text-sm font-medium text-gray-800">
                主要缺陷
                <select
                  disabled={resettingJudgment}
                  value={optionalChoice(operation.primary_defect_type_mode, operation.primary_defect_type_id ? String(operation.primary_defect_type_id) : null)}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value === "preserve" || value === "clear") {
                      updateOperation({ primary_defect_type_mode: value, primary_defect_type_id: null });
                    } else {
                      updateOperation({ primary_defect_type_mode: "set", primary_defect_type_id: Number(value.replace("set:", "")) });
                    }
                  }}
                  className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm disabled:bg-gray-100"
                >
                  <option value="preserve">保留原主要缺陷</option>
                  <option value="clear">清空主要缺陷</option>
                  {allowsType && activeDefectTypes.map((item) => <option key={item.id} value={`set:${item.id}`}>设置为 {item.name}</option>)}
                </select>
              </label>
            </div>

            <div className="space-y-3 rounded-xl border border-line p-4">
              <label className="block space-y-2 text-sm font-medium text-gray-800">
                缺陷类型
                <select disabled={resettingJudgment} value={operation.defect_types_mode} onChange={(event) => changeDefectTypesMode(event.target.value as BatchDefectTypesMode)} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm disabled:bg-gray-100">
                  <option value="preserve">保留全部原类型</option>
                  {allowsType && <option value="append">追加到原类型</option>}
                  {allowsType && <option value="replace">替换全部原类型</option>}
                  <option value="clear">清空全部类型</option>
                </select>
              </label>
              {(operation.defect_types_mode === "append" || operation.defect_types_mode === "replace") && (
                <div className="grid max-h-40 gap-2 overflow-y-auto sm:grid-cols-2">
                  {activeDefectTypes.map((item) => (
                    <label key={item.id} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm">
                      <input type="checkbox" checked={operation.defect_type_ids.includes(item.id)} onChange={() => toggleDefectType(item.id)} />
                      <span className={item.parent_id ? "pl-3" : "font-medium"}>{item.name}</span>
                    </label>
                  ))}
                  {activeDefectTypes.length === 0 && <p className="text-xs text-gray-500">当前没有可用缺陷类型。</p>}
                </div>
              )}
            </div>

            <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
              <label className="space-y-2 text-sm font-medium text-gray-800">
                备注
                <select
                  disabled={resettingJudgment}
                  value={operation.triage_note_mode}
                  onChange={(event) => updateOperation({ triage_note_mode: event.target.value as BatchFieldMode, triage_note: event.target.value === "set" ? operation.triage_note : null })}
                  className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm disabled:bg-gray-100"
                >
                  <option value="preserve">保留原备注</option>
                  <option value="set">设置统一备注</option>
                  <option value="clear">清空备注</option>
                </select>
              </label>
              {operation.triage_note_mode === "set" && (
                <label className="space-y-2 text-sm font-medium text-gray-800">
                  统一备注内容
                  <textarea value={operation.triage_note ?? ""} onChange={(event) => updateOperation({ triage_note: event.target.value })} rows={3} maxLength={4000} className="w-full resize-y rounded-lg border border-line px-3 py-2 text-sm" placeholder="将写入所有选中图片" />
                </label>
              )}
            </div>
          </section>
        )}

        {error && <div className="flex gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"><AlertTriangle size={18} className="shrink-0" />{error}</div>}
        {success && <div className="flex gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"><CheckCircle2 size={18} className="shrink-0" />{success}</div>}

        {preview && (
          <section className="space-y-3" aria-labelledby="batch-triage-preview">
            <h3 id="batch-triage-preview" className="text-sm font-semibold text-ink">2. 确认逐项预览</h3>
            <div className={`rounded-xl border p-4 ${preview.can_apply ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
              <div className="flex items-start gap-2">
                {preview.can_apply ? <CheckCircle2 size={18} className="text-emerald-700" /> : <AlertTriangle size={18} className="text-amber-700" />}
                <div>
                  <div className="text-sm font-semibold">{preview.can_apply ? `可以更新 ${preview.changed} 张图片` : preview.blocked > 0 ? `${preview.blocked} 张图片被阻断` : "没有需要写入的变化"}</div>
                  <div className="mt-1 text-xs text-gray-600">选中 {preview.requested} · 将变化 {preview.changed} · 无需变化 {preview.unchanged} · 阻断 {preview.blocked}</div>
                </div>
              </div>
            </div>
            <div className="max-h-72 divide-y divide-line overflow-y-auto rounded-xl border border-line">
              {preview.items.map((item) => (
                <div key={item.sample_id} className="space-y-1 px-3 py-3 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate font-medium text-gray-900" title={item.relative_path}>{item.relative_path}</span>
                    <span className={item.errors.length > 0 ? "shrink-0 font-semibold text-red-700" : item.changed ? "shrink-0 font-semibold text-emerald-700" : "shrink-0 text-gray-500"}>{item.errors.length > 0 ? "已阻断" : item.changed ? "将修改" : "无变化"}</span>
                  </div>
                  <div className="text-gray-500">原值：{stateLabel(item.before, defectTypeMap)}</div>
                  {item.after && <div className="text-gray-700">新值：{stateLabel(item.after, defectTypeMap)}</div>}
                  {item.errors.map((message) => <div key={message} className="font-medium text-red-700">{message}</div>)}
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="flex flex-col-reverse gap-2 border-t border-line pt-4 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="min-h-10 rounded-lg border border-line px-4 text-sm font-medium">关闭</button>
          <button type="button" onClick={() => void runPreview()} disabled={loading || previewing || submitting || !hasOperation || selectedSampleIds.length === 0 || selectedSampleIds.length > 200} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-gray-300 px-4 text-sm font-semibold text-gray-800 disabled:cursor-not-allowed disabled:text-gray-300">
            {previewing ? <LoaderCircle size={17} className="animate-spin" /> : <Eye size={17} />}
            {previewing ? "预览中" : preview ? "重新预览" : "预览变更"}
          </button>
          <button type="button" onClick={() => void applyPreview()} disabled={!preview?.can_apply || previewing || submitting} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-gray-300">
            {submitting ? <LoaderCircle size={17} className="animate-spin" /> : <Save size={17} />}
            {submitting ? "提交中" : "确认应用"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
