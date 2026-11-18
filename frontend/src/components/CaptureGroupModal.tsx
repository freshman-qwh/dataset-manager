import axios from "axios";
import { useEffect, useState } from "react";
import { confirmCaptureGroups, getFilenameGroupRule, getIndustrialPlan, listSamples, previewCaptureGroups } from "../api/client";
import { getOrganization } from "../api/organization";
import type { FrozenPlan, GroupPreviewRequest } from "../types/industrial";
import type { DatasetBatch } from "../types/organization";

export default function CaptureGroupModal({ datasetId, selectedIds, onClose, onUpdated }: {
  datasetId: number; selectedIds: number[]; onClose: () => void; onUpdated: () => Promise<void>;
}) {
  const [request, setRequest] = useState<GroupPreviewRequest>({ mode: selectedIds.length ? "selected" : "filename", scope: selectedIds.length ? "selected" : "all", capture_group_id: "", capture_batch_id: "", filename_rule: {delimiter:"_", keep_segments:2, include_parent:false}, remember_rule:true });
  const [batches, setBatches] = useState<DatasetBatch[]>([]);
  const [scopeCount, setScopeCount] = useState<number | null>(null);
  const [scopeError, setScopeError] = useState("");
  const [scopeVersion, setScopeVersion] = useState(0);
  const [plan, setPlan] = useState<FrozenPlan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { let alive=true; void getFilenameGroupRule(datasetId).then(rule => { if (alive && rule) setRequest(v => ({...v, filename_rule:rule})); }).catch(() => undefined); return () => {alive=false;}; }, [datasetId]);
  useEffect(() => {
    const controller = new AbortController();
    void getOrganization(datasetId, controller.signal).then(value => setBatches(value.batches)).catch(() => undefined);
    return () => controller.abort();
  }, [datasetId]);
  useEffect(() => {
    setScopeCount(null);
    setScopeError("");
    if (request.scope === "selected") {
      setScopeCount(selectedIds.length);
      return;
    }
    if (request.scope === "batch" && !request.scope_capture_batch_id?.trim()) return;
    const controller = new AbortController();
    void listSamples({
      datasetId,
      fileType: "image",
      captureBatchId: request.scope === "batch" ? request.scope_capture_batch_id?.trim() : undefined,
      pageSize: 1
    }, controller.signal).then(value => {
      if (!controller.signal.aborted) setScopeCount(value.total);
    }).catch(() => {
      if (!controller.signal.aborted) setScopeError("范围图片数量读取失败，请重试。");
    });
    return () => controller.abort();
  }, [datasetId, request.scope, request.scope_capture_batch_id, selectedIds.length, scopeVersion]);
  function change(values: Partial<GroupPreviewRequest>) { setRequest(v => ({ ...v, ...values })); setPlan(null); setConfirmation(""); setError(""); }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(axios.isAxiosError(e) ? String(e.response?.data?.detail ?? "请求未完成，可重试确认；同一计划不会重复写入。") : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }
  let scopeDescription = "正在读取范围图片数量…";
  if (scopeCount !== null) {
    scopeDescription = request.scope === "all"
      ? `全数据集 ${scopeCount} 张图片参与规则检查。确认后将更新预览列出的原工件分组。`
      : `范围内共 ${scopeCount} 张图片，预览将列出实际写入内容。`;
  } else if (request.scope === "batch" && !request.scope_capture_batch_id?.trim()) {
    scopeDescription = "请选择或填写范围采集批次编号。";
  }
  let frozenScopeLabel = "全数据集";
  if (plan?.summary.scope === "selected") frozenScopeLabel = "所选图片";
  if (plan?.summary.scope === "batch") frozenScopeLabel = `采集批次 ${String(plan.summary.scope_capture_batch_id)}`;
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"><section role="dialog" aria-modal="true" aria-labelledby="capture-group-title" className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
    <div className="flex justify-between gap-4"><h2 id="capture-group-title" className="text-xl font-semibold">采集工件与批次</h2><button disabled={busy} onClick={onClose}>关闭</button></div>
    <p className="my-3 text-sm text-gray-600">同一工件的多视角、连拍图片应属于同一组。批次用于区分重复的工件编号。分组只写入本地元数据。</p>
    <fieldset disabled={busy} className="space-y-3">
      <div className="space-y-3 rounded-lg border border-line p-3">
        <label className="block text-sm">分组范围
          <select aria-label="分组范围" className="mt-1 w-full rounded-lg border p-2" value={request.scope} onChange={e => change({ scope: e.target.value as GroupPreviewRequest["scope"], scope_capture_batch_id: undefined })}>
            <option value="selected" disabled={selectedIds.length === 0}>所选图片（{selectedIds.length} 张）</option>
            <option value="batch">指定采集批次</option>
            <option value="all">全数据集</option>
          </select>
        </label>
        {request.scope === "batch" && <label className="block text-sm">范围采集批次编号
          <input aria-label="范围采集批次编号" list={`group-scope-batches-${datasetId}`} maxLength={160} className="mt-1 w-full rounded-lg border p-2" value={request.scope_capture_batch_id ?? ""} onChange={e => change({ scope_capture_batch_id: e.target.value })} placeholder="选择已有批次或输入精确编号" />
          <datalist id={`group-scope-batches-${datasetId}`}>{batches.map(batch => <option key={batch.id} value={batch.code}>{batch.name}</option>)}</datalist>
        </label>}
        <p role="status" className="text-sm text-gray-600">{scopeDescription}</p>
        {scopeError && <p role="alert" className="text-sm text-red-700">{scopeError}<button type="button" className="ml-2 underline" onClick={() => setScopeVersion(value => value + 1)}>重试读取数量</button></p>}
      </div>
      <select aria-label="分组方式" className="w-full rounded-lg border p-2" value={request.mode} onChange={e => change({ mode: e.target.value as GroupPreviewRequest["mode"], clear_capture_batch: false })}>
        <option value="selected">统一设置工件号</option><option value="filename">从文件名提取工件号</option><option value="directories">按直接父目录生成分组草稿</option><option value="mapping">导入 CSV / JSON 映射</option>
      </select>
      {request.mode === "filename" && <div className="space-y-3 rounded-lg bg-gray-50 p-3"><p className="text-sm">示例 part_001_camA → 按 _ 分隔、保留前 2 段 → part_001。同一工件不同视角应得到相同编号。</p><div className="flex flex-wrap items-center gap-3 text-sm"><label>分隔符<select aria-label="工件名分隔符" className="ml-2 rounded border p-2" value={request.filename_rule?.delimiter ?? "_"} onChange={e => change({filename_rule:{...request.filename_rule!, delimiter:e.target.value as "_"|"-"|" "}})}><option value="_">下划线 _</option><option value="-">短横线 -</option><option value=" ">空格</option></select></label><label>保留前几段<input aria-label="保留段数" type="number" min={1} max={8} className="ml-2 w-16 rounded border p-2" value={request.filename_rule?.keep_segments ?? 2} onChange={e => change({filename_rule:{...request.filename_rule!, keep_segments:Number(e.target.value)}})} /></label></div><label className="block text-sm"><input type="checkbox" checked={request.filename_rule?.include_parent ?? false} onChange={e => change({filename_rule:{...request.filename_rule!, include_parent:e.target.checked}})} /> 编号包含父目录，区分不同目录下同名工件</label><label className="block text-sm"><input type="checkbox" checked={request.remember_rule ?? true} onChange={e => change({remember_rule:e.target.checked})} /> 确认后记住此提取规则，供后续批次复用</label></div>}
      {request.mode === "selected" && <label className="block text-sm">工件 / 采集组编号<input aria-label="工件编号" maxLength={160} className="mt-1 w-full rounded-lg border p-2" value={request.capture_group_id ?? ""} onChange={e => change({ capture_group_id: e.target.value })} placeholder="留空表示清除此字段" /></label>}
      {request.mode !== "mapping" ? <>
        <label className="block text-sm">写入采集批次编号（可选）
          <input aria-label="采集批次" maxLength={160} className="mt-1 w-full rounded-lg border p-2 disabled:bg-gray-50" value={request.capture_batch_id ?? ""} disabled={request.clear_capture_batch} onChange={e => change({ capture_batch_id: e.target.value })} placeholder="留空保留原有批次" />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={request.clear_capture_batch ?? false} onChange={e => change({ clear_capture_batch: e.target.checked, capture_batch_id: "" })} />
          清除这批图片的采集批次
        </label>
      </> : <>
        <label className="block text-sm">选择映射文件<input className="ml-2" type="file" accept=".csv,.json" onChange={e => { const file = e.target.files?.[0]; if (file && file.size <= 2_000_000) void file.text().then(mapping_text => change({ mapping_text })); else setError("请选择不超过 2 MB 的映射文件。"); }} /></label>
        <textarea aria-label="映射内容" className="h-28 w-full rounded-lg border p-2 font-mono text-xs" value={request.mapping_text ?? ""} onChange={e => change({ mapping_text: e.target.value })} placeholder={'relative_path,capture_group_id,capture_batch_id\npart/a.png,part-1,batch-1'} />
        <div className="grid gap-2 sm:grid-cols-3">{(["path_column", "group_column", "batch_column"] as const).map((key, i) => <label key={key} className="text-xs">{["相对路径列（精确匹配）", "工件列", "批次列（可缺省）"][i]}<input className="mt-1 w-full rounded border p-2" value={request[key] ?? ["relative_path", "capture_group_id", "capture_batch_id"][i]} onChange={e => change({ [key]: e.target.value })} /></label>)}</div>
        <p className="text-xs text-gray-500">按当前范围内的相对路径精确匹配，范围外的映射行会要求修正。批次列留空或省略时，保留该图片原有采集批次。</p>
      </>}
      {request.mode === "directories" && <p className="text-sm text-amber-800">目录只是草稿。请确认同目录图片确属同一工件；按 OK/NG 分类的目录不能作为工件组。</p>}
      <button disabled={scopeCount === null || scopeCount === 0 || Boolean(scopeError)} className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40" onClick={() => void run(async () => { setPlan(await previewCaptureGroups(datasetId, { ...request, sample_ids: request.scope === "selected" ? selectedIds : [] })); setConfirmation(""); })}>{busy ? "处理中…" : "预览分组变更"}</button>
    </fieldset>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    {plan && <div className="mt-4 space-y-3 border-t pt-4">
      <p className="text-sm font-medium">已冻结范围 · {frozenScopeLabel} · {String(plan.summary.scope_sample_count)} 张图片</p>
      <p className="text-sm">涉及 {plan.total} 张图片，{String(plan.summary.group_count)} 个工件/批次组合；已有划分 {String(plan.summary.existing_split_count)} 张。已有划分保持原值，后续训练准备重新检查隔离。</p>
      <div className="max-h-60 overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{["图片", "原组 / 批次", "新组 / 批次", "现有划分"].map(v => <th key={v} className="p-2">{v}</th>)}</tr></thead><tbody>{plan.rows.map(r => <tr key={r.sample_id} className="border-t">
        <td className="p-2">{r.relative_path}</td>
        <td className="p-2">{r.before_group ?? "—"} / {r.before_batch ?? "—"}</td>
        <td className="p-2">{r.capture_group_id ?? "清除"} / {r.batch_action === "keep"
          ? r.capture_batch_id ? `${r.capture_batch_id}（保留）` : "保留原值"
          : r.capture_batch_id ?? "清除"}</td>
        <td className="p-2">{r.split ?? "未划分"}</td>
      </tr>)}</tbody></table></div>
      <div className="flex gap-3 text-sm"><button disabled={busy || plan.page === 1} onClick={() => void run(async () => setPlan(await getIndustrialPlan(datasetId, plan.plan_id, plan.page - 1)))}>上一页</button><span>第 {plan.page} 页 / {Math.ceil(plan.total / plan.page_size)}</span><button disabled={busy || plan.page * plan.page_size >= plan.total} onClick={() => void run(async () => setPlan(await getIndustrialPlan(datasetId, plan.plan_id, plan.page + 1)))}>下一页</button></div>
      <label className="block text-sm">输入“{plan.confirmation}”<input aria-label="分组确认文字" className="mt-1 w-full rounded-lg border p-2" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label>
      <button disabled={busy || confirmation !== plan.confirmation} className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40" onClick={() => void run(async () => { await confirmCaptureGroups(datasetId, plan, confirmation); await onUpdated(); onClose(); })}>确认写入分组</button>
    </div>}
  </section></div>;
}
