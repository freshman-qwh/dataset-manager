import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getIndustrialPlan, listDatasets } from "../api/client";
import { getOrganization } from "../api/organization";
import { createValidationRun, previewValidationBatch, validationError } from "../api/validation";
import type { Dataset } from "../types/dataset";
import type { FrozenPlan } from "../types/industrial";
import type { DatasetBatch } from "../types/organization";
import type { ValidationBatchPreviewRequest } from "../types/validation";

export default function ValidationBatchModal({ runId, onClose }: { runId: string; onClose: () => void }) {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [target, setTarget] = useState(0);
  const [batches, setBatches] = useState<DatasetBatch[] | null>(null);
  const [batchChoice, setBatchChoice] = useState("");
  const [batchError, setBatchError] = useState("");
  const [batchRefresh, setBatchRefresh] = useState(0);
  const [independent, setIndependent] = useState(false);
  const [plan, setPlan] = useState<FrozenPlan | null>(null);
  const [name, setName] = useState("新批次验证");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void listDatasets()
      .then(items => { if (alive) setDatasets(items.filter(item => item.workflow_profile === "industrial_anomaly")); })
      .catch(cause => { if (alive) setError(validationError(cause)); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!target) return;
    const controller = new AbortController();
    setBatchError("");
    void getOrganization(target, controller.signal)
      .then(value => { if (!controller.signal.aborted) setBatches(value.batches); })
      .catch(cause => { if (!controller.signal.aborted) setBatchError(validationError(cause)); });
    return () => controller.abort();
  }, [target, batchRefresh]);

  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try { await fn(); }
    catch (cause) { setError(validationError(cause)); }
    finally { setBusy(false); }
  }

  async function checkBatch() {
    setPlan(null);
    const payload: ValidationBatchPreviewRequest = {
      target_dataset_id: target,
      batch_scope: batchChoice === "all" || batchChoice === "unassigned" ? batchChoice : "batch",
      independent_capture_declared: independent,
    };
    if (payload.batch_scope === "batch") payload.batch_id = Number(batchChoice);
    setPlan(await previewValidationBatch(runId, payload));
  }

  async function changePage(page: number) {
    if (plan) setPlan(await getIndustrialPlan(target, plan.plan_id, page));
  }

  const pageCount = plan ? Math.max(1, Math.ceil(plan.total / plan.page_size)) : 1;
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
    <section role="dialog" aria-modal="true" aria-labelledby="batch-title" className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
      <div className="flex justify-between gap-4">
        <h2 id="batch-title" className="text-lg font-semibold">用此模型验证新批次</h2>
        <button onClick={onClose} disabled={busy} className="text-sm text-gray-500">关闭</button>
      </div>
      <p className="my-4 text-sm leading-6 text-gray-500">先扫描新图片并指定采集批次，再选择本次范围。检查会排除与原输入及历史批次重叠的内容和采集组，并沿用原模型、ROI、热图标尺与阈值。</p>
      {error && <p role="alert" className="my-3 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <fieldset disabled={busy} className="space-y-4">
        <label className="block text-sm">新批次所在数据集
          <select aria-label="新批次项目" className="mt-1 w-full rounded-lg border p-2" value={target} onChange={event => {
            setTarget(Number(event.target.value));
            setBatches(null);
            setBatchChoice("");
            setBatchError("");
            setPlan(null);
            setError("");
          }}>
            <option value={0}>请选择工业数据集</option>
            {datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
          </select>
        </label>
        <label className="block text-sm">采集批次范围
          <select aria-label="采集批次范围" className="mt-1 w-full rounded-lg border p-2" value={batchChoice} disabled={!target || !batches} onChange={event => {
            setBatchChoice(event.target.value);
            setPlan(null);
            setError("");
          }}>
            <option value="">{target && !batches ? "正在读取采集批次…" : "请选择本次范围"}</option>
            {batches?.map(batch => <option key={batch.id} value={batch.id}>{batch.name} · {batch.sample_count} 张</option>)}
            <option value="unassigned">未分配批次的图片</option>
            <option value="all">全部图片（跨批次）</option>
          </select>
        </label>
        {batchError && <p role="alert" className="text-sm text-red-700">
          采集批次读取失败。{batchError}
          <button type="button" className="ml-2 underline" onClick={() => setBatchRefresh(value => value + 1)}>重新读取批次</button>
        </p>}
        <p className="text-xs leading-5 text-gray-500">具体批次仅纳入该批次的图片。整组隔离检查仍覆盖整个数据集；同组存在范围外图片时，会将范围内成员排除。</p>
        <label className="block text-sm">
          <input type="checkbox" checked={independent} onChange={event => { setIndependent(event.target.checked); setPlan(null); }} />
          {" "}未填写工件组的图片均来自独立采集，没有同工件连拍或多视角
        </label>
        <label className="block text-sm">批次记录名称
          <input aria-label="批次记录名称" className="mt-1 w-full rounded-lg border p-2" maxLength={160} value={name} onChange={event => setName(event.target.value)} />
        </label>
        <button disabled={!target || !batchChoice || !batches || busy} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-40" onClick={() => void action(checkBatch)}>检查新批次</button>
      </fieldset>
      {plan && <div className="mt-4 space-y-3 border-t pt-4">
        <p className="break-words text-sm font-medium">本次范围 · {String(plan.summary.scope_label)}</p>
        <p className="text-sm">纳入 {String(plan.summary.included_count)} 张 · 排除 {String(plan.summary.excluded_count)} 张 · 未知人工真值 {String(plan.summary.unknown_count)} 张</p>
        <p className="text-sm text-gray-500">{String(plan.summary.notice)} 原冻结阈值 {Number(plan.summary.threshold).toPrecision(6)}。</p>
        {(plan.summary.blockers as string[]).map(text => <p key={text} role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-800">{text}</p>)}
        <details open className="text-xs text-gray-500">
          <summary className="cursor-pointer">逐图检查结果 · 共 {plan.total} 张</summary>
          <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto">
            {plan.rows.map(row => <li key={String(row.sample_id)} className="break-all">{String(row.relative_path)} · {String(row.exclusion_reason ?? "纳入预测")}</li>)}
          </ul>
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <button type="button" disabled={busy || plan.page <= 1} className="min-h-9 underline disabled:opacity-40" onClick={() => void action(() => changePage(plan.page - 1))}>上一页</button>
            <span>第 {plan.page} / {pageCount} 页 · 共 {plan.total} 张</span>
            <button type="button" disabled={busy || plan.page >= pageCount} className="min-h-9 underline disabled:opacity-40" onClick={() => void action(() => changePage(plan.page + 1))}>下一页</button>
          </div>
        </details>
        <button disabled={busy || plan.summary.blocked !== false || !name.trim()} className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40" onClick={() => void action(async () => {
          await createValidationRun(target, plan, name.trim());
          window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
          navigate(`/datasets/${target}/validate`);
        })}>{busy ? "正在创建…" : "确认新批次，仅运行预测"}</button>
      </div>}
    </section>
  </div>;
}
