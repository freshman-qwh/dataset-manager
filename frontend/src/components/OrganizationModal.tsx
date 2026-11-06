import { useEffect, useState } from "react";
import { assignOrganization, createBatch, createCategory, deleteBatch, deleteCategory, getOrganization, organizationError, updateBatch, updateCategory } from "../api/organization";
import type { DatasetOrganization } from "../types/organization";
import Modal from "./Modal";

interface Props { datasetId: number; open: boolean; onClose: () => void; onUpdated: () => Promise<void> | void; selectedIds?: number[]; }
const inputStyle = "w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm";
const buttonStyle = "rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40";

export default function OrganizationModal({ datasetId, open, onClose, onUpdated, selectedIds = [] }: Props) {
  const [data, setData] = useState<DatasetOrganization | null>(null);
  const [tab, setTab] = useState<"categories" | "batches">("categories");
  const [editId, setEditId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [capturedAt, setCapturedAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [category, setCategory] = useState("keep");
  const [batch, setBatch] = useState("keep");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    if (!open) return;
    setData(null); setError("");
    const controller = new AbortController();
    void getOrganization(datasetId, controller.signal).then(setData).catch((caught) => { if (!controller.signal.aborted) setError(organizationError(caught, "无法加载类别和批次。")); });
    return () => controller.abort();
  }, [datasetId, open, version]);
  useEffect(() => { if (open) {setEditId(null); setName(""); setDescription(""); setCapturedAt(""); setCategory("keep"); setBatch("keep"); setSuccess("");} }, [open, datasetId, tab]);

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setSuccess("");
    try { await action(); await onUpdated(); setVersion((value) => value + 1); }
    catch (caught) { setError(organizationError(caught, "保存失败，请重试。")); }
    finally { setBusy(false); }
  }

  async function save() {
    await run(async () => {
      if (tab === "categories") {
        const payload = { name: name.trim(), description: description.trim() || null };
        if (editId === null) await createCategory(datasetId, payload); else await updateCategory(datasetId, editId, payload);
      } else {
        const payload = { name: name.trim(), notes: description.trim() || null, captured_at: capturedAt || null };
        if (editId === null) await createBatch(datasetId, payload); else await updateBatch(datasetId, editId, payload);
      }
      setEditId(null); setName(""); setDescription(""); setCapturedAt(""); setSuccess("已保存");
    });
  }

  return <Modal open={open} title="类别与批次" onClose={onClose} size="lg" dismissible={!busy}><div className="space-y-5 p-5">
    <p className="text-sm leading-6 text-gray-500">类别表示产品或对象，批次表示哪一次采集；文件夹保留原始位置，普通标签可另行补充。</p>
    {selectedIds.length > 0 && <section className="space-y-3 rounded-lg border border-line bg-gray-50 p-4"><h3 className="text-sm font-medium text-gray-800">设置所选 {selectedIds.length} 张图片</h3><div className="grid gap-3 sm:grid-cols-2"><label className="text-xs text-gray-500">对象类别<select aria-label="所选图片类别" value={category} onChange={(event) => setCategory(event.target.value)} className={`${inputStyle} mt-1`}><option value="keep">保持不变</option><option value="clear">清除类别归属</option>{data?.categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="text-xs text-gray-500">采集批次<select aria-label="所选图片批次" value={batch} onChange={(event) => setBatch(event.target.value)} className={`${inputStyle} mt-1`}><option value="keep">保持不变</option><option value="clear">清除批次归属</option>{data?.batches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div><p className="text-xs text-gray-500">保留工件组、判定和原图；只修改明确选择的归属。</p><button type="button" disabled={busy || !data || (category === "keep" && batch === "keep")} className={buttonStyle} onClick={() => void run(async () => { await assignOrganization(datasetId, { sample_ids: selectedIds, ...(category !== "keep" ? { category_id: category === "clear" ? null : Number(category) } : {}), ...(batch !== "keep" ? { batch_id: batch === "clear" ? null : Number(batch) } : {}) }); setCategory("keep"); setBatch("keep"); setSuccess("所选图片归属已更新"); })}>应用到所选图片</button></section>}
    <div className="flex gap-1 border-b border-line">{(["categories", "batches"] as const).map((value) => <button type="button" key={value} onClick={() => setTab(value)} className={`border-b-2 px-4 py-2 text-sm ${tab === value ? "border-gray-900 font-medium text-gray-900" : "border-transparent text-gray-500"}`}>{value === "categories" ? "对象类别" : "采集批次"}</button>)}</div>
    {data ? <div className="max-h-52 space-y-2 overflow-y-auto">{(tab === "categories" ? data.categories : data.batches).map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line p-3"><div className="min-w-0"><p className="break-words text-sm font-medium text-gray-700">{item.name}</p><p className="mt-1 text-xs text-gray-400">{item.sample_count ?? 0} 张图片</p></div><div className="flex gap-2"><button type="button" disabled={busy} onClick={() => { setEditId(item.id); setName(item.name); setDescription("description" in item ? item.description ?? "" : item.notes ?? ""); setCapturedAt("captured_at" in item ? item.captured_at?.slice(0, 10) ?? "" : ""); }} className={buttonStyle}>编辑</button><button type="button" disabled={busy || item.sample_count > 0} title={item.sample_count > 0 ? "仍有图片归属，请先调整图片后再删除" : "删除未使用项"} onClick={() => void run(async () => { if (tab === "categories") await deleteCategory(datasetId, item.id); else await deleteBatch(datasetId, item.id); setSuccess("未使用项已删除"); })} className={buttonStyle}>删除</button></div></div>)}{(tab === "categories" ? data.categories : data.batches).length === 0 && <p className="p-4 text-center text-sm text-gray-400">暂无{tab === "categories" ? "对象类别" : "采集批次"}</p>}</div> : !error && <p className="text-sm text-gray-400">正在加载…</p>}
    <form onSubmit={(event) => { event.preventDefault(); void save(); }} className="space-y-3 rounded-lg border border-line p-4"><h3 className="text-sm font-medium text-gray-700">{editId === null ? "新增" : "编辑"}{tab === "categories" ? "类别" : "批次"}</h3><label className="block text-xs text-gray-500">名称<input aria-label={tab === "categories" ? "类别名称" : "批次名称"} required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder={tab === "categories" ? "例如 bottle、探针型号 A" : "例如 首次采集、补充异常"} className={`${inputStyle} mt-1`} /></label>{tab === "batches" && <label className="block text-xs text-gray-500">采集日期（可选）<input aria-label="采集日期" type="date" value={capturedAt} onChange={(event) => setCapturedAt(event.target.value)} className={`${inputStyle} mt-1`} /></label>}<label className="block text-xs text-gray-500">{tab === "categories" ? "描述" : "备注"}（可选）<input aria-label={tab === "categories" ? "类别描述" : "批次备注"} maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} className={`${inputStyle} mt-1`} /></label><div className="flex gap-2"><button type="submit" disabled={busy || !name.trim()} className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40">{busy ? "保存中…" : editId === null ? "添加" : "保存修改"}</button>{editId !== null && <button type="button" onClick={() => {setEditId(null); setName(""); setDescription(""); setCapturedAt("");}} className={buttonStyle}>取消编辑</button>}</div></form>
    {error && <p role="alert" className="text-sm text-red-700">{error} {!data && <button type="button" className="ml-2 underline" onClick={() => setVersion((value) => value + 1)}>重试</button>}</p>}{success && <p role="status" className="text-sm text-gray-600">{success}</p>}
  </div></Modal>;
}
