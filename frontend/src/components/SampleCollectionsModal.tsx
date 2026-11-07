import axios from "axios";
import { Download, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createSampleCollection, deleteSampleCollection, getSampleCollection, listSampleCollections, updateSampleCollection } from "../api/sampleCollections";
import type { CollectionItem, CollectionItemInput, SampleCollection } from "../types/sampleCollections";
import { renderSampleCollection } from "../utils/renderSampleCollection";
import { getSampleFileUrl } from "../api/client";
import Modal from "./Modal";

interface Props { open: boolean; sampleIds: number[]; onClose: () => void }
const button = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40";
const itemInput = (item: CollectionItem): CollectionItemInput => ({ sample_id: item.sample_id, file_hash: item.file_hash, verdict: item.verdict, note: item.note });
function message(error: unknown): string {
  const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" ? detail : error instanceof Error && !axios.isAxiosError(error) ? error.message : "操作失败，请检查服务后重试。未保存内容已保留。";
}
function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function SampleCollectionsModal({ open, sampleIds, onClose }: Props) {
  const [collections, setCollections] = useState<SampleCollection[]>([]);
  const [current, setCurrent] = useState<SampleCollection | null>(null);
  const [name, setName] = useState("");
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [newName, setNewName] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pageSize, setPageSize] = useState<4 | 9 | 16>(9);
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<{ url: string; collection: SampleCollection; page: number; size: 4 | 9 | 16 } | null>(null);
  const [leave, setLeave] = useState<number | "close" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [failedImages, setFailedImages] = useState<Set<number>>(new Set());
  const generation = useRef<AbortController | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const closeRef = useRef<() => void>(() => undefined);
  const dirty = Boolean(current && (name !== current.name || JSON.stringify(items.map(itemInput)) !== JSON.stringify(current.items.map(itemInput))));
  const uniqueIds = [...new Set(sampleIds)];
  const missingIds = uniqueIds.filter((id) => !items.some((item) => item.sample_id === id));
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  const pageEntries = items.slice((page - 1) * pageSize, page * pageSize);
  const invalidate = () => setPreview(null);

  function select(collection: SampleCollection | null) {
    setCurrent(collection); setName(collection?.name ?? ""); setItems(collection?.items ?? []);
    setPage(1); setPreview(null); setLeave(null); setDeleting(false); setFailedImages(new Set());
  }
  function accept(collection: SampleCollection) {
    setCollections((values) => [collection, ...values.filter((entry) => entry.id !== collection.id)]);
    select(collection);
  }
  async function refresh() {
    if (busy || loading) return;
    setLoading(true); setError("");
    try { const values = await listSampleCollections({ kind: "basket" }); setCollections(values); select(values.find((entry) => entry.id === current?.id) ?? values[0] ?? null); setNotice(""); }
    catch (failure) { setError(message(failure)); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setError(""); setNotice(""); setNewName(""); select(null);
    void listSampleCollections({ kind: "basket" }, controller.signal).then((values) => { if (!controller.signal.aborted) { setCollections(values); select(values[0] ?? null); } }).catch((failure) => { if (!controller.signal.aborted) setError(message(failure)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); generation.current?.abort(); };
  }, [open]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url); }, [preview]);
  function requestLeave(target: number | "close") {
    if (busy || loading) return;
    if (dirty || newName.trim()) { setLeave(target); return; }
    finishLeave(target);
  }
  function finishLeave(target: number | "close") {
    setNewName(""); setLeave(null);
    if (target === "close") onClose(); else select(collections.find((entry) => entry.id === target) ?? null);
  }
  closeRef.current = () => requestLeave("close");
  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow; document.body.style.overflow = "hidden";
    const dialog = container.current?.closest('[role="dialog"]'); dialog?.querySelector<HTMLElement>("button")?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href]') ?? []);
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus(); }
      if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus(); }
    };
    document.addEventListener("keydown", handler);
    return () => { document.removeEventListener("keydown", handler); document.body.style.overflow = previousOverflow; previousFocus?.focus(); };
  }, [open]);

  async function save(): Promise<boolean> {
    if (!current || busy || !name.trim()) return false;
    setBusy(true); setError("");
    try { accept(await updateSampleCollection(current.id, { expected_version: current.version, name: name.trim(), items: items.map(itemInput) })); setNotice("集合已保存。"); return true; }
    catch (failure) { setError(message(failure)); return false; }
    finally { setBusy(false); }
  }
  async function create() {
    if (busy || !newName.trim()) return;
    setBusy(true); setError("");
    try {
      const collection = await createSampleCollection({ name: newName.trim(), kind: "basket" });
      accept(collection); setNewName(""); setNotice("收集篮已创建。可加入当前选中的图片。");
    } catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  }
  async function addSelected() {
    if (!current || busy || !missingIds.length) return;
    setBusy(true); setError("");
    try {
      accept(await updateSampleCollection(current.id, { expected_version: current.version, name: name.trim(), items: [...items.map(itemInput), ...missingIds.map((sample_id) => ({ sample_id }))] }));
      setNotice(`已加入 ${missingIds.length} 张图片。`);
    } catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  }
  async function removeCollection() {
    if (!current || busy) return;
    setBusy(true); setError("");
    try { await deleteSampleCollection(current.id, current.version); const remaining = collections.filter((entry) => entry.id !== current.id); setCollections(remaining); select(remaining[0] ?? null); setNotice("集合已删除，原图片保留。"); }
    catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  }
  async function generate() {
    if (!current || busy || dirty) return;
    setBusy(true); setError(""); setPreview(null);
    const controller = new AbortController(); generation.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 60000);
    try {
      const latest = await getSampleCollection(current.id, controller.signal);
      if (latest.version !== current.version) throw new Error("集合已在其他页面更新，请重新加载后生成。");
      const blob = await renderSampleCollection(latest, page, pageSize, controller.signal);
      if (!controller.signal.aborted) setPreview({ url: URL.createObjectURL(blob), collection: latest, page, size: pageSize });
    } catch (failure) { if (open) setError(controller.signal.aborted ? "生成已取消或超时，请重试。" : message(failure)); }
    finally { window.clearTimeout(timeout); setBusy(false); }
  }
  function downloadManifest() {
    if (!preview) return;
    const collection = preview.collection;
    download(new Blob([JSON.stringify({ format_version: 1, collection_id: collection.id, collection_version: collection.version, name: collection.name, page: preview.page, page_size: preview.size, generated_at: new Date().toISOString(), excluded: [], items: collection.items.slice((preview.page - 1) * preview.size, preview.page * preview.size).map((item, index) => ({ number: (preview.page - 1) * preview.size + index + 1, sample_id: item.sample_id, dataset_id: item.dataset_id, filename: item.filename, relative_path: item.relative_path, absolute_path: item.sample?.absolute_path, file_hash: item.file_hash, category_id: item.sample?.category_id, batch_id: item.sample?.batch_id, note: item.note, verdict: item.verdict })) }, null, 2)], { type: "application/json" }), `collection-${collection.id}-page-${preview.page}-sources.json`);
  }
  return <Modal open={open} title="样本收集篮" onClose={() => requestLeave("close")} size="xl"><div ref={container} className="space-y-4 p-3 sm:p-5">
    <p className="text-xs leading-5 text-gray-500">跨文件夹、跨数据集收集案例，最多 100 张。保存的是图片引用，可添加说明并生成 4 / 9 / 16 宫格 PNG。</p>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="text-sm text-green-800">{notice}</p>}
    {leave !== null && <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><p>有未保存内容，请保存或放弃后继续。</p><div className="flex flex-wrap gap-2"><button type="button" disabled={busy || !current || Boolean(newName.trim())} className={button} onClick={() => { const target = leave; void save().then((saved) => { if (saved) finishLeave(target); }); }}>保存并继续</button><button type="button" disabled={busy} className={button} onClick={() => finishLeave(leave)}>放弃修改</button><button type="button" className={button} onClick={() => setLeave(null)}>取消</button></div>{newName.trim() && <p className="text-xs">新建名称尚未提交，可取消后点击“新建”。</p>}</div>}
    <div className="grid gap-2 sm:grid-cols-[1fr_auto]"><select aria-label="选择收集篮" disabled={busy || loading} value={current?.id ?? ""} onChange={(event) => requestLeave(Number(event.target.value))} className="min-h-10 min-w-0 rounded-lg border border-line bg-white px-3 text-sm"><option value="" disabled>{loading ? "正在读取…" : "选择收集篮"}</option>{collections.map((entry) => <option key={entry.id} value={entry.id}>{entry.name} · {entry.items.length} 张</option>)}</select><button type="button" disabled={busy || loading || dirty || Boolean(newName.trim())} className={button} onClick={() => void refresh()}><RefreshCw size={15} />重新加载</button></div>
    <div className="flex flex-wrap gap-2"><input aria-label="新收集篮名称" maxLength={160} value={newName} disabled={busy || dirty} onChange={(event) => setNewName(event.target.value)} placeholder="新收集篮名称" className="min-h-10 min-w-0 flex-1 rounded-lg border border-line px-3 text-sm" /><button type="button" disabled={busy || loading || dirty || !newName.trim()} onClick={() => void create()} className={button}><Plus size={15} />新建</button></div>
    {current ? <>
      <div className="flex flex-wrap items-center gap-2"><input aria-label="收集篮名称" disabled={busy} maxLength={160} value={name} onChange={(event) => { setName(event.target.value); invalidate(); }} className="min-h-10 min-w-0 flex-1 rounded-lg border border-line px-3 text-sm" /><button type="button" disabled={busy || !dirty || !name.trim()} onClick={() => void save()} className={button}>保存修改{dirty ? " *" : ""}</button><button type="button" disabled={busy} onClick={() => setDeleting(true)} aria-label="删除收集篮" className={button}><Trash2 size={15} /></button></div>
      {deleting && <div className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 p-3 text-sm"><span>删除此集合？其中的图片仍保留。</span><button type="button" disabled={busy} className={button} onClick={() => void removeCollection()}>确认删除集合</button><button type="button" className={button} onClick={() => setDeleting(false)}>取消</button></div>}
      {uniqueIds.length > 0 && <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-gray-50 p-3 text-sm"><span>浏览页选中 {uniqueIds.length} 张，{missingIds.length} 张尚未加入。</span><button type="button" disabled={busy || !missingIds.length || items.length + missingIds.length > 100 || !name.trim()} onClick={() => void addSelected()} className={button}>加入当前收集篮</button>{items.length + missingIds.length > 100 && <span className="text-red-700">超过 100 张，请减少选择或新建收集篮。</span>}</div>}
      <div className="max-h-96 space-y-2 overflow-y-auto rounded-lg border border-line p-2" aria-label="收集图片列表">{items.length === 0 && <p className="p-5 text-center text-sm text-gray-500">还没有图片。返回浏览页选择图片后，可加入此收集篮。</p>}{items.map((item, index) => <div key={item.sample_id} className="flex items-start gap-3 rounded-lg border border-line p-2"><div className="h-16 w-16 shrink-0 overflow-hidden rounded bg-gray-100">{item.sample && !item.unavailable_reason ? <img src={getSampleFileUrl(item.sample_id)} alt={item.filename} className="h-full w-full object-contain" onError={(event) => { event.currentTarget.style.visibility = "hidden"; setFailedImages((values) => new Set([...values, item.sample_id])); }} /> : <span className="p-1 text-xs text-gray-500">不可用</span>}</div><div className="min-w-0 flex-1"><p className="break-all text-xs font-medium">{index + 1}. {item.filename}</p><p className="truncate text-xs text-gray-400" title={item.relative_path}>{item.relative_path} · 数据集 #{item.dataset_id}</p>{(item.unavailable_reason || failedImages.has(item.sample_id)) && <p className="text-xs text-amber-800">{item.unavailable_reason || "预览读取失败，请检查原文件后重新加载。"}</p>}<input aria-label={`图片 ${index + 1} 说明`} value={item.note} maxLength={500} disabled={busy} onChange={(event) => { setItems((values) => values.map((entry) => entry.sample_id === item.sample_id ? { ...entry, note: event.target.value } : entry)); invalidate(); }} placeholder="添加案例说明" className="mt-1 min-h-9 w-full rounded border border-line px-2 text-xs" /></div><button type="button" disabled={busy} aria-label={`移除图片 ${index + 1}`} onClick={() => { setItems((values) => values.filter((entry) => entry.sample_id !== item.sample_id)); setPage(1); invalidate(); }} className="rounded p-2 text-gray-500 hover:bg-gray-100"><Trash2 size={15} /></button></div>)}</div>
      <div className="flex flex-wrap items-center gap-2"><select aria-label="拼版布局" disabled={busy} value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value) as 4 | 9 | 16); setPage(1); invalidate(); }} className="min-h-10 rounded-lg border border-line px-2 text-sm"><option value={4}>4 宫格</option><option value={9}>9 宫格</option><option value={16}>16 宫格</option></select><select aria-label="拼版页码" value={page} disabled={busy} onChange={(event) => { setPage(Number(event.target.value)); invalidate(); }} className="min-h-10 rounded-lg border border-line px-2 text-sm">{Array.from({ length: pages }, (_, index) => <option key={index} value={index + 1}>第 {index + 1} / {pages} 页</option>)}</select><button type="button" disabled={busy || dirty || !pageEntries.length || pageEntries.some((item) => item.unavailable_reason)} className={button} onClick={() => void generate()}>{busy ? "处理中…" : "生成本页拼版"}</button>{dirty && <span className="text-xs text-gray-500">请先保存修改。</span>}</div>
      {preview && <><img src={preview.url} alt={`收集篮第 ${preview.page} 页拼版`} className="max-h-96 w-full rounded-lg border border-line object-contain" /><div className="flex flex-wrap gap-2"><a href={preview.url} download={`collection-${preview.collection.id}-page-${preview.page}.png`} className={button}><Download size={15} />下载本页 PNG</a><button type="button" className={button} onClick={downloadManifest}>下载本页来源清单 JSON</button></div><p className="text-xs text-gray-500">来源清单包含完整文件路径，请按需要分享。每页单独下载，避免浏览器拦截批量下载。</p></>}
    </> : !loading && <p className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-gray-500">先新建一个收集篮，再加入所选图片。</p>}
  </div></Modal>;
}
