import { useEffect, useRef, useState } from "react";
import { commitTrainingSplit, previewTrainingSplit } from "../api/client";
import type { TrainingSplit, TrainingSplitPreview, TrainingSplitRequest } from "../types/trainingSplit";

interface Props {
  datasetId: number;
  includeEmpty: boolean;
  onConfirmed: (sampleIds: number[], revision: number) => void;
  onInvalidate: () => void;
}

const DEFAULT_REQUEST: TrainingSplitRequest = {
  train_ratio: 80, val_ratio: 10, test_ratio: 10, include_test: true,
  include_empty: true, triage_filter: "all", seed: 42, overrides: {}, page: 1, page_size: 25
};

const EXCLUSION_LABELS: Record<string, string> = {
  unavailable: "文件不可用",
  rejected: "审核拒绝",
  unfinished: "标注未完成",
  empty_disabled: "未包含确认空图",
  triage_mismatch: "分拣不匹配",
  triage_outdated: "分拣已过期"
};

const TRIAGE_LABELS: Record<string, string> = {
  untriaged: "未分拣",
  pending: "待确认",
  ok: "OK",
  ng: "NG"
};

export default function TrainingSplitPlanner({ datasetId, includeEmpty, onConfirmed, onInvalidate }: Props) {
  const [request, setRequest] = useState<TrainingSplitRequest>({ ...DEFAULT_REQUEST, include_empty: includeEmpty });
  const [preview, setPreview] = useState<TrainingSplitPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const requestVersion = useRef(0);

  useEffect(() => {
    requestVersion.current += 1;
    setRequest((current) => ({ ...current, include_empty: includeEmpty, overrides: {}, page: 1 }));
    setPreview(null);
    setConfirmed(null);
  }, [includeEmpty]);

  async function load(next: TrainingSplitRequest) {
    if (confirmed !== null) onInvalidate();
    const version = requestVersion.current;
    setBusy(true);
    setError(null);
    setConfirmed(null);
    try {
      const result = await previewTrainingSplit(datasetId, next);
      if (version === requestVersion.current) {
        setRequest(next);
        setPreview(result);
      }
    } catch {
      if (version === requestVersion.current) {
        setPreview(null);
        setError("划分预览失败，请检查比例与当前数据后重试。");
      }
    } finally {
      setBusy(false);
    }
  }

  function change<K extends keyof TrainingSplitRequest>(key: K, value: TrainingSplitRequest[K]) {
    requestVersion.current += 1;
    onInvalidate();
    setRequest((current) => ({ ...current, [key]: value, overrides: key === "triage_filter" || key === "include_test" ? {} : current.overrides, page: 1 }));
    setPreview(null);
    setConfirmed(null);
  }

  async function confirm() {
    if (!preview || preview.blocked) return;
    const version = requestVersion.current;
    setBusy(true);
    setError(null);
    try {
      const result = await commitTrainingSplit(datasetId, { ...request, fingerprint: preview.fingerprint });
      if (version !== requestVersion.current) {
        setPreview(null);
        setError("确认期间条件发生变化，请重新预览当前划分。");
        return;
      }
      onConfirmed(result.sample_ids, result.dataset_revision);
      setConfirmed(`已确认 ${result.sample_ids.length} 张图片，写入 ${result.updated} 项划分；导出将使用此范围。`);
      setPreview(null);
    } catch {
      setPreview(null);
      setError("数据或划分已变化，或仍有重复冲突。请重新预览后确认。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-white p-4" aria-label="训练划分建议">
      <h3 className="text-sm font-semibold text-ink">训练划分建议</h3>
      <p className="mt-1 text-xs leading-5 text-gray-500">从已完成标注的正常图片中建议 train/val/test；保留已有划分，同内容图片整组处理。快速分拣只控制纳入范围。</p>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {(["train_ratio", "val_ratio", "test_ratio"] as const).map((key) => (
          <label key={key} className="text-xs text-gray-600">
            {key === "train_ratio" ? "train" : key === "val_ratio" ? "val" : "test"} 比例
            <input type="number" min="0" disabled={busy || (key === "test_ratio" && !request.include_test)} value={request[key]}
              onChange={(event) => change(key, Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-line px-2 py-2 text-sm" />
          </label>
        ))}
        <label className="text-xs text-gray-600">随机种子
          <input type="number" disabled={busy} value={request.seed} onChange={(event) => change("seed", Number(event.target.value))}
            className="mt-1 w-full rounded-lg border border-line px-2 py-2 text-sm" />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-gray-600">
        <label><input type="checkbox" disabled={busy} checked={request.include_test} onChange={(event) => change("include_test", event.target.checked)} /> 启用 test</label>
        <label>快速分拣条件 <select disabled={busy} value={request.triage_filter} onChange={(event) => change("triage_filter", event.target.value as TrainingSplitRequest["triage_filter"])} className="rounded border border-line bg-white px-2 py-1">
          <option value="all">不限</option><option value="ok">仅 OK</option><option value="ng">仅 NG</option>
        </select></label>
      </div>
      <button type="button" disabled={busy || request.train_ratio <= 0} onClick={() => void load(request)}
        className="mt-3 rounded-lg border border-line px-3 py-2 text-xs font-semibold hover:bg-gray-50 disabled:opacity-50">
        {busy ? "处理中…" : preview ? "重新计算预览" : "预览划分"}
      </button>
      {error && <p role="alert" className="mt-3 text-xs text-red-700">{error}</p>}
      {confirmed && <p role="status" className="mt-3 text-xs text-emerald-700">{confirmed}</p>}
      {preview && <div className="mt-4 space-y-3">
        <div className="rounded-lg bg-gray-50 p-3 text-xs leading-6 text-gray-700">
          候选 {preview.candidate_count} · 未划分 {preview.unassigned_count} · 重复组 {preview.duplicate_group_count} · 将变更 {preview.change_count}<br />
          建议：train {preview.split_counts.train} / val {preview.split_counts.val} / test {preview.split_counts.test}
          {Object.entries(preview.excluded_counts).length > 0 && <div className="text-gray-500">
            未纳入：{Object.entries(preview.excluded_counts).map(([reason, count]) => `${EXCLUSION_LABELS[reason] ?? reason} ${count}`).join(" · ")}
          </div>}
        </div>
        {preview.warnings.map((warning, index) => <p key={index} className="text-xs text-amber-700">{warning}</p>)}
        <div className="max-h-72 overflow-auto rounded-lg border border-line">
          {preview.rows.map((row) => <div key={row.sample_id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2 text-xs last:border-0">
            <div className="min-w-0 flex-1"><div className="truncate font-medium" title={row.relative_path}>{row.relative_path}</div>
              <div className="text-gray-500">原划分 {row.current_split ?? "未划分"} · {row.annotation_progress === "completed_empty" ? "确认无目标" : "已完成标注"} · 分拣 {TRIAGE_LABELS[row.triage_status] ?? row.triage_status}{row.duplicate_count > 1 ? ` · 同内容 ${row.duplicate_count} 张` : ""}</div>
              {row.warning && <div className="text-amber-700">{row.warning}</div>}
            </div>
            <select aria-label={`${row.relative_path} 建议划分`} disabled={busy} value={row.suggested_split ?? "excluded"}
              onChange={(event) => change("overrides", { ...request.overrides, [row.sample_id]: event.target.value === "excluded" ? null : event.target.value as TrainingSplit })}
              className="rounded border border-line bg-white px-2 py-1">
              <option value="train">train</option><option value="val">val</option><option value="test" disabled={!request.include_test}>test</option><option value="excluded">本次排除</option>
            </select>
          </div>)}
        </div>
        <div className="flex items-center justify-between text-xs text-gray-500">
          <button type="button" disabled={busy || preview.page <= 1} onClick={() => void load({ ...request, page: preview.page - 1 })}>上一页</button>
          第 {preview.page} / {preview.page_count} 页
          <button type="button" disabled={busy || preview.page >= preview.page_count} onClick={() => void load({ ...request, page: preview.page + 1 })}>下一页</button>
        </div>
        <button type="button" disabled={busy || preview.blocked} onClick={() => void confirm()}
          className="rounded-lg bg-gray-900 px-3 py-2 text-xs font-semibold text-white disabled:bg-gray-300">确认写入划分</button>
      </div>}
    </section>
  );
}
