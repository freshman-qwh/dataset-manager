import axios from "axios";
import { useEffect, useState } from "react";
import { confirmCaptureGroups, getFilenameGroupRule, getIndustrialPlan, previewCaptureGroups } from "../api/client";
import type { FrozenPlan, GroupPreviewRequest } from "../types/industrial";

export default function CaptureGroupModal({ datasetId, selectedIds, onClose, onUpdated }: {
  datasetId: number; selectedIds: number[]; onClose: () => void; onUpdated: () => Promise<void>;
}) {
  const [request, setRequest] = useState<GroupPreviewRequest>({ mode: selectedIds.length ? "selected" : "filename", capture_group_id: "", capture_batch_id: "", filename_rule: {delimiter:"_", keep_segments:2, include_parent:false}, remember_rule:true });
  const [plan, setPlan] = useState<FrozenPlan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { let alive=true; void getFilenameGroupRule(datasetId).then(rule => { if (alive && rule) setRequest(v => ({...v, filename_rule:rule})); }).catch(() => undefined); return () => {alive=false;}; }, [datasetId]);
  function change(values: Partial<GroupPreviewRequest>) { setRequest(v => ({ ...v, ...values })); setPlan(null); setConfirmation(""); setError(""); }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(axios.isAxiosError(e) ? String(e.response?.data?.detail ?? "请求未完成，可重试确认；同一计划不会重复写入。") : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"><section role="dialog" aria-modal="true" aria-labelledby="capture-group-title" className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
    <div className="flex justify-between gap-4"><h2 id="capture-group-title" className="text-xl font-semibold">采集工件与批次</h2><button disabled={busy} onClick={onClose}>关闭</button></div>
    <p className="my-3 text-sm text-gray-600">同一工件的多视角、连拍图片应属于同一组。批次用于区分重复的工件编号。分组只写入本地元数据。</p>
    <fieldset disabled={busy} className="space-y-3">
      <select aria-label="分组方式" className="w-full rounded-lg border p-2" value={request.mode} onChange={e => change({ mode: e.target.value as GroupPreviewRequest["mode"] })}>
        <option value="selected">所选 {selectedIds.length} 张图片设置同一工件</option><option value="filename">从文件名提取工件号</option><option value="directories">按直接父目录生成全项目草稿</option><option value="mapping">导入 CSV / JSON 映射</option>
      </select>
      {request.mode === "filename" && <div className="space-y-3 rounded-lg bg-gray-50 p-3"><p className="text-sm">示例 part_001_camA → 按 _ 分隔、保留前 2 段 → part_001。同一工件不同视角应得到相同编号。</p><div className="flex flex-wrap items-center gap-3 text-sm"><label>分隔符<select aria-label="工件名分隔符" className="ml-2 rounded border p-2" value={request.filename_rule?.delimiter ?? "_"} onChange={e => change({filename_rule:{...request.filename_rule!, delimiter:e.target.value as "_"|"-"|" "}})}><option value="_">下划线 _</option><option value="-">短横线 -</option><option value=" ">空格</option></select></label><label>保留前几段<input aria-label="保留段数" type="number" min={1} max={8} className="ml-2 w-16 rounded border p-2" value={request.filename_rule?.keep_segments ?? 2} onChange={e => change({filename_rule:{...request.filename_rule!, keep_segments:Number(e.target.value)}})} /></label></div><label className="block text-sm"><input type="checkbox" checked={request.filename_rule?.include_parent ?? false} onChange={e => change({filename_rule:{...request.filename_rule!, include_parent:e.target.checked}})} /> 编号包含父目录，区分不同目录下同名工件</label><label className="block text-sm"><input type="checkbox" checked={request.remember_rule ?? true} onChange={e => change({remember_rule:e.target.checked})} /> 确认后记住此提取规则，供后续批次复用</label></div>}
      {request.mode === "selected" && <label className="block text-sm">工件 / 采集组编号<input aria-label="工件编号" maxLength={160} className="mt-1 w-full rounded-lg border p-2" value={request.capture_group_id ?? ""} onChange={e => change({ capture_group_id: e.target.value })} placeholder="留空表示清除此字段" /></label>}
      {request.mode !== "mapping" ? <label className="block text-sm">采集批次<input aria-label="采集批次" maxLength={160} className="mt-1 w-full rounded-lg border p-2" value={request.capture_batch_id ?? ""} onChange={e => change({ capture_batch_id: e.target.value })} placeholder="留空表示清除此字段" /></label> : <>
        <label className="block text-sm">选择映射文件<input className="ml-2" type="file" accept=".csv,.json" onChange={e => { const file = e.target.files?.[0]; if (file && file.size <= 2_000_000) void file.text().then(mapping_text => change({ mapping_text })); else setError("请选择不超过 2 MB 的映射文件。"); }} /></label>
        <textarea aria-label="映射内容" className="h-28 w-full rounded-lg border p-2 font-mono text-xs" value={request.mapping_text ?? ""} onChange={e => change({ mapping_text: e.target.value })} placeholder={'relative_path,capture_group_id,capture_batch_id\npart/a.png,part-1,batch-1'} />
        <div className="grid gap-2 sm:grid-cols-3">{(["path_column", "group_column", "batch_column"] as const).map((key, i) => <label key={key} className="text-xs">{["相对路径列（精确匹配）", "工件列", "批次列（可缺省）"][i]}<input className="mt-1 w-full rounded border p-2" value={request[key] ?? ["relative_path", "capture_group_id", "capture_batch_id"][i]} onChange={e => change({ [key]: e.target.value })} /></label>)}</div>
      </>}
      {request.mode === "directories" && <p className="text-sm text-amber-800">目录只是草稿。请确认同目录图片确属同一工件；按 OK/NG 分类的目录不能作为工件组。</p>}
      <button className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white" onClick={() => void run(async () => { setPlan(await previewCaptureGroups(datasetId, { ...request, sample_ids: selectedIds })); setConfirmation(""); })}>{busy ? "处理中…" : "预览分组变更"}</button>
    </fieldset>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    {plan && <div className="mt-4 space-y-3 border-t pt-4">
      <p className="text-sm">涉及 {plan.total} 张图片，{String(plan.summary.group_count)} 个工件/批次组合；已有划分 {String(plan.summary.existing_split_count)} 张。已有划分保持原值，后续训练准备重新检查隔离。</p>
      <div className="max-h-60 overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{["图片", "原组 / 批次", "新组 / 批次", "现有划分"].map(v => <th key={v} className="p-2">{v}</th>)}</tr></thead><tbody>{plan.rows.map(r => <tr key={r.sample_id} className="border-t"><td className="p-2">{r.relative_path}</td><td className="p-2">{r.before_group ?? "—"} / {r.before_batch ?? "—"}</td><td className="p-2">{r.capture_group_id ?? "清除"} / {r.capture_batch_id ?? "清除"}</td><td className="p-2">{r.split ?? "未划分"}</td></tr>)}</tbody></table></div>
      <div className="flex gap-3 text-sm"><button disabled={busy || plan.page === 1} onClick={() => void run(async () => setPlan(await getIndustrialPlan(datasetId, plan.plan_id, plan.page - 1)))}>上一页</button><span>第 {plan.page} 页 / {Math.ceil(plan.total / plan.page_size)}</span><button disabled={busy || plan.page * plan.page_size >= plan.total} onClick={() => void run(async () => setPlan(await getIndustrialPlan(datasetId, plan.plan_id, plan.page + 1)))}>下一页</button></div>
      <label className="block text-sm">输入“{plan.confirmation}”<input aria-label="分组确认文字" className="mt-1 w-full rounded-lg border p-2" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label>
      <button disabled={busy || confirmation !== plan.confirmation} className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40" onClick={() => void run(async () => { await confirmCaptureGroups(datasetId, plan, confirmation); await onUpdated(); onClose(); })}>确认写入分组</button>
    </div>}
  </section></div>;
}
