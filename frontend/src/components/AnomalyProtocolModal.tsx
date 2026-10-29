import axios from "axios";
import { useState } from "react";
import { confirmAnomalySplits, getIndustrialPlan, previewAnomalyProtocol } from "../api/client";
import type { AnnotationExportSampleQuery } from "../types/annotationExport";
import type { FrozenPlan } from "../types/industrial";

export default function AnomalyProtocolModal({ datasetId, currentQuery, selectedIds, onClose, onUpdated }: {
  datasetId: number; currentQuery: AnnotationExportSampleQuery; selectedIds: number[];
  onClose: () => void; onUpdated: () => Promise<void>;
}) {
  const [scope, setScope] = useState("all");
  const [independent, setIndependent] = useState(false);
  const [borderline, setBorderline] = useState(false);
  const [preserve, setPreserve] = useState(false);
  const [ratios, setRatios] = useState([80, 10, 10]);
  const [abnormalPercent, setAbnormalPercent] = useState(50);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [overrideDirty, setOverrideDirty] = useState(false);
  const [plan, setPlan] = useState<FrozenPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [step, setStep] = useState(1);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(axios.isAxiosError(e) ? String(e.response?.data?.detail ?? "请求未完成，可重试或重新预览。") : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }
  function invalidate() { setPlan(null); setConfirmation(""); }
  async function preview() {
    const sample_query = scope === "selected" ? { sample_ids: selectedIds } : scope === "current" ? currentQuery : {};
    const next = await previewAnomalyProtocol(datasetId, { sample_query, independent_capture_declared: independent,
      include_borderline_evaluation: borderline, normal_ratios: ratios, abnormal_val_percent: abnormalPercent,
      preserve_existing: preserve, overrides: Object.fromEntries(Object.entries(overrides).filter(([, value]) => value)) });
    setOverrideDirty(false); setPlan(next); setConfirmation(""); setStep(2);
  }
  const blocked = plan?.summary.blocked !== false;
  const counts = plan?.summary.counts as Record<string, { normal: number; abnormal: number }> | undefined;
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"><section role="dialog" aria-modal="true" aria-labelledby="anomaly-title" className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
    <div className="flex justify-between"><h2 id="anomaly-title" className="text-xl font-semibold">准备异常检测数据</h2><button disabled={busy} onClick={onClose}>关闭</button></div>
    <p className="my-3 text-sm text-gray-600">1 选择数据与规则 → 2 检查整组划分 → 3 导出训练包。图像级协议，无需几何标注。</p>
    <nav className="mb-4 flex gap-3 text-sm">{[1, 2, 3].map(n => <button key={n} className={step === n ? "font-semibold underline" : "text-gray-500"} disabled={busy || n > 1 && !plan} onClick={() => setStep(n)}>第 {n} 步</button>)}</nav>
    {step === 1 && <fieldset disabled={busy} className="space-y-4">
      <label className="block text-sm">数据范围<select aria-label="协议数据范围" className="ml-2 rounded-lg border p-2" value={scope} onChange={e => { setScope(e.target.value); setOverrides({}); invalidate(); }}><option value="all">项目全部图片</option><option value="current">当前筛选</option><option value="selected" disabled={!selectedIds.length}>所选 {selectedIds.length} 张</option></select></label>
      <p className="text-xs text-gray-500">无论选择哪种范围，都检查整个项目中的工件与重复关系；范围外有同组成员时整组排除。</p>
      <label className="block text-sm"><input type="checkbox" checked={independent} onChange={e => { setIndependent(e.target.checked); invalidate(); }} /> 我确认未填写工件组的图片来自相互独立的采集，不含同一工件的多视角或连拍</label>
      <label className="block text-sm"><input type="checkbox" checked={borderline} onChange={e => { setBorderline(e.target.checked); invalidate(); }} /> 将有效临界 OK 显式纳入验证/测试，仍禁止进入训练</label>
      <label className="block text-sm"><input type="checkbox" checked={preserve} onChange={e => { setPreserve(e.target.checked); invalidate(); }} /> 保留已有划分并检查整组约束（有冲突时需调整整组）</label>
      <div className="flex flex-wrap items-center gap-3 text-sm">正常图片建议比例{ratios.map((value, i) => <label key={i}>{["train", "val", "test"][i]} %<input aria-label={`正常 ${["train", "val", "test"][i]} 百分比`} type="number" min={1} max={98} className="ml-1 w-16 rounded border p-2" value={value} onChange={e => { setRatios(v => v.map((old, index) => index === i ? Number(e.target.value) : old)); invalidate(); }} /></label>)}</div>
      <label className="block text-sm">异常图片验证集占比 %<input type="number" min={1} max={99} className="ml-2 w-20 rounded border p-2" value={abnormalPercent} onChange={e => { setAbnormalPercent(Number(e.target.value)); invalidate(); }} />，其余进入测试；训练异常始终为 0。</label>
      <button className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white" onClick={() => void run(preview)}>{busy ? "正在检查原图和分组…" : "检查并预览划分"}</button>
    </fieldset>}
    {plan && step === 2 && <div className="space-y-3">
      <p className="text-sm">全项目检查 {String(plan.summary.full_dataset_checked)} 个文件；本次 {plan.total} 张，纳入 {String(plan.summary.included_count)} 张，排除 {String(plan.summary.excluded_count)} 张。现有划分尚未修改。</p>
      {counts && <div className="grid grid-cols-3 gap-2">{Object.entries(counts).map(([key, c]) => <div key={key} className="rounded-lg border p-3 text-sm"><strong>{key}</strong><p>正常 {c.normal} / 异常 {c.abnormal}</p></div>)}</div>}
      {(plan.summary.blockers as string[]).map(v => <p role="alert" key={v} className="rounded-lg bg-amber-50 p-2 text-sm text-amber-900">{v}</p>)}
      <div className="max-h-64 overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{["图片 / 采集工件", "合并组", "建议 / 排除原因", "整组调整"].map(v => <th key={v} className="p-2">{v}</th>)}</tr></thead><tbody>{plan.rows.map(r => <tr key={r.sample_id} className="border-t"><td className="p-2">{r.relative_path}<p className="text-gray-500">{r.capture_batch_id ?? "—"} / {r.capture_group_id ?? "未填写"}</p></td><td className="p-2">{r.group_id}</td><td className="p-2">{r.exclusion_reason || `${r.split} · ${r.label_index === 1 ? "异常" : "正常"}`}</td><td className="p-2"><select aria-label={`调整组 ${r.group_id} 图片 ${r.sample_id}`} className="rounded border p-1" disabled={busy} value={overrides[String(r.group_id)] ?? ""} onChange={e => { setOverrides(v => ({ ...v, [String(r.group_id)]: e.target.value })); setOverrideDirty(true); }}><option value="">自动</option><option value="train">train</option><option value="val">val</option><option value="test">test</option><option value="exclude">排除整组</option></select></td></tr>)}</tbody></table></div>
      <div className="flex gap-4 text-sm"><button disabled={busy || plan.page === 1} onClick={() => void run(async () => setPlan(await getIndustrialPlan(datasetId, plan.plan_id, plan.page - 1)))}>上一页</button><span>{plan.page} / {Math.ceil(plan.total / plan.page_size)}</span><button disabled={busy || plan.page * plan.page_size >= plan.total} onClick={() => void run(async () => setPlan(await getIndustrialPlan(datasetId, plan.plan_id, plan.page + 1)))}>下一页</button><button disabled={busy} className="underline" onClick={() => void run(preview)}>应用整组调整并重新检查</button></div>
      <p className="text-xs text-gray-500">调整后须重新检查。训练仅允许全员有效完全 OK；同组或相同内容不会拆开用于凑比例。</p>
      <button disabled={busy || blocked || overrideDirty} className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40" onClick={() => setStep(3)}>使用此冻结计划</button>
    </div>}
    {plan && step === 3 && <div className="space-y-4">
      <p className="text-sm">计划 {plan.plan_id.slice(0, 8)} · 项目版本 {plan.dataset_revision} · 24 小时内有效。数据或标准变化后需要重新检查。</p>
      <p className="text-sm">默认直接用计划导出，不改项目中的 split。只有需要在项目内保留本次划分时，才使用下面的确认。</p>
      <div id="anomaly-export-actions"><p className="text-sm text-gray-500">下一阶段在此接入训练包导出。</p></div>
      <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">可选：将本次划分写回项目</summary><label className="mt-3 block text-sm">输入“{plan.confirmation}”<input aria-label="划分确认文字" className="mt-1 w-full rounded-lg border p-2" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button disabled={busy || blocked || confirmation !== plan.confirmation} className="mt-3 rounded-lg border px-4 py-2 text-sm disabled:opacity-40" onClick={() => void run(async () => { const result = await confirmAnomalySplits(datasetId, plan, confirmation); setPlan(await getIndustrialPlan(datasetId, result.plan_id)); setConfirmation(""); await onUpdated(); })}>确认整批写回划分</button></details>
    </div>}
    {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
    {busy && <p role="status" className="mt-3 text-sm">正在处理，请稍候…</p>}
  </section></div>;
}
