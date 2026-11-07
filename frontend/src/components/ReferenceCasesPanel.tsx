import { BookOpen, Loader2, Plus, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getSampleFileUrl } from "../api/client";
import { getOrganization, organizationError } from "../api/organization";
import { createSampleCollection, listSampleCollections, updateSampleCollection } from "../api/sampleCollections";
import type { Sample } from "../types/dataset";
import type { SampleCollection, CollectionItem, ReferenceVerdict } from "../types/sampleCollections";
import LocalBrowseThumbnail from "./LocalBrowseThumbnail";

const VERDICT_LABELS: Record<ReferenceVerdict, string> = {
  acceptable: "可接受",
  unacceptable: "不可接受",
  uncertain: "待确认"
};
const VERDICT_STYLES: Record<ReferenceVerdict, string> = {
  acceptable: "border-emerald-200 bg-emerald-50 text-emerald-800",
  unacceptable: "border-red-200 bg-red-50 text-red-800",
  uncertain: "border-violet-200 bg-violet-50 text-violet-800"
};

interface Props {
  datasetId: number;
  currentSample: Sample | null;
  onClose: () => void;
}

function writeItems(items: CollectionItem[]) {
  return items.map((item) => ({ sample_id: item.sample_id, file_hash: item.file_hash, verdict: item.verdict, note: item.note }));
}

export default function ReferenceCasesPanel({ datasetId, currentSample, onClose }: Props) {
  const categoryId = currentSample?.category_id ?? null;
  const [collections, setCollections] = useState<SampleCollection[]>([]);
  const [categoryName, setCategoryName] = useState(categoryId ? `类别 ${categoryId}` : "未分类");
  const [allCategories, setAllCategories] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<ReferenceVerdict>("uncertain");
  const [note, setNote] = useState("");
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState<{ collectionId: number; sampleId: number } | null>(null);
  const [preview, setPreview] = useState<Sample | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const collectionsRef = useRef<SampleCollection[]>([]);
  collectionsRef.current = collections;
  const savingRef = useRef(false);
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  const scopeRef = useRef(0);
  const closeRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    let active = true;
    const scope = ++scopeRef.current;
    setLoading(true);
    setError(null);
    void listSampleCollections({ kind: "reference", dataset_id: datasetId }).then((value) => {
      if (active && scope === scopeRef.current) setCollections(value);
    }).catch((loadError: unknown) => {
      if (active) setError(organizationError(loadError, "参考卡加载失败，请重试。"));
    }).finally(() => { if (active) setLoading(false); });
    void getOrganization(datasetId).then((value) => {
      if (active) setCategoryName(categoryId ? value.categories.find((item) => item.id === categoryId)?.name ?? `类别 ${categoryId}` : "未分类");
    }).catch(() => undefined);
    return () => { active = false; scopeRef.current += 1; };
  }, [datasetId, categoryId, version]);

  function requestAction(action: () => void) {
    if (savingRef.current) return;
    if (dirtyRef.current) setPendingAction(() => action);
    else action();
  }
  closeRef.current = () => requestAction(onClose);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!dirtyRef.current && !savingRef.current) return;
      event.preventDefault(); event.returnValue = "";
    }
    window.addEventListener("beforeunload", beforeUnload);
    return () => { document.body.style.overflow = overflow; previousFocus?.focus(); window.removeEventListener("beforeunload", beforeUnload); };
  }, []);

  useEffect(() => {
    const selector = preview ? '[data-reference-preview="true"]' : pendingAction ? '[data-reference-leave="true"]' : '[data-reference-main="true"]';
    const root = container.current?.querySelector<HTMLElement>(selector);
    root?.querySelector<HTMLButtonElement>("button")?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (savingRef.current) return;
        if (preview) { setPreview(null); return; }
        if (pendingAction) { setPendingAction(null); return; }
        closeRef.current();
      }
      if (event.key !== "Tab") return;
      const elements = Array.from(root?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href]') ?? []);
      const first = elements[0]; const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pendingAction, preview]);

  const visibleCollections = collections.filter((item) => allCategories || item.category_id === categoryId);
  const visibleCards = visibleCollections.flatMap((collection) => collection.items.map((item) => ({ collection, item })));
  const editingCollection = editing ? collections.find((item) => item.id === editing.collectionId) : null;
  const editingItem = editingCollection?.items.find((item) => item.sample_id === editing?.sampleId);
  const targetSample = editingItem?.sample ?? (editing ? null : currentSample);

  function resetForm() { setEditing(null); setVerdict("uncertain"); setNote(""); setDirty(false); }

  async function saveCard(): Promise<boolean> {
    if (!targetSample || savingRef.current || loading) return false;
    if (!note.trim()) { setError("请写一句解释，说明可接受或不可接受的依据。"); return false; }
    if (targetSample.file_status !== "normal") { setError("原图不可用，请先修复文件后再保存参考卡。"); return false; }
    const scope = scopeRef.current;
    savingRef.current = true; setSaving(true); setError(null); setNotice(null);
    try {
      const existing = editingCollection ?? collections.find((item) => item.category_id === categoryId);
      const newItem = { sample_id: targetSample.id, file_hash: targetSample.file_hash, verdict, note: note.trim() };
      let saved: SampleCollection;
      if (existing) {
        const previous = existing.items.filter((item) => item.sample_id !== targetSample.id);
        saved = await updateSampleCollection(existing.id, { expected_version: existing.version, items: [...writeItems(previous), newItem] });
      } else {
        saved = await createSampleCollection({ name: `${categoryName} · 边界案例`, kind: "reference", dataset_id: datasetId, ...(categoryId ? { category_id: categoryId } : {}), items: [newItem] });
      }
      if (scope !== scopeRef.current) return false;
      const nextCollections = [...collectionsRef.current.filter((item) => item.id !== saved.id), saved];
      collectionsRef.current = nextCollections;
      setCollections(nextCollections);
      setDirty(false); setNotice("参考卡已保存；分拣判定未改变。");
      resetForm();
      return true;
    } catch (saveError: unknown) {
      if (scope === scopeRef.current) setError(organizationError(saveError, "参考卡保存失败。若已在其他窗口修改，请刷新后重试。"));
      return false;
    } finally { savingRef.current = false; setSaving(false); }
  }

  async function removeCard(collection: SampleCollection, item: CollectionItem) {
    if (savingRef.current) return;
    savingRef.current = true; setSaving(true); setError(null); setNotice(null);
    try {
      // A save-and-continue action may have updated this collection locally.
      // Keep that version, while still rejecting changes from other windows.
      const latest = collectionsRef.current.find((value) => value.id === collection.id) ?? collection;
      const saved = await updateSampleCollection(latest.id, { expected_version: latest.version, items: writeItems(latest.items.filter((value) => value.sample_id !== item.sample_id)) });
      setCollections((current) => current.map((value) => value.id === saved.id ? saved : value));
      if (editing?.sampleId === item.sample_id && editing.collectionId === collection.id) resetForm();
      setNotice("已移除参考卡，原图和分拣判定保留。" );
    } catch (removeError: unknown) { setError(organizationError(removeError, "移除失败，请刷新参考卡后重试。")); }
    finally { savingRef.current = false; setSaving(false); }
  }

  return <div ref={container} className="fixed inset-0 z-40 flex items-center justify-center bg-black/20 p-2 backdrop-blur-sm sm:p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) requestAction(onClose); }}>
    <section data-reference-main="true" role="dialog" aria-modal="true" aria-label="边界案例参考卡" className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-line bg-white shadow-soft">
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3"><div className="min-w-0"><h2 className="flex items-center gap-2 text-base font-semibold"><BookOpen size={18} />边界案例参考卡</h2><p className="mt-1 break-words text-xs text-gray-500">当前类别：{categoryName} · 参考卡单独保存，供人工对照判定。</p></div><button type="button" disabled={saving} onClick={() => requestAction(onClose)} aria-label="关闭参考卡" className="shrink-0 rounded-lg p-2 text-gray-500 hover:bg-gray-100 disabled:opacity-40"><X size={19} /></button></header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {error && <div role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
        {notice && <p role="status" className="mb-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
        <div className="rounded-lg border border-line bg-gray-50 p-3">
          <h3 className="text-sm font-semibold">{editing ? "编辑参考卡" : "将当前图片加入参考卡"}</h3>
          <p className="mt-1 break-all text-xs text-gray-500">{targetSample?.filename ?? "当前没有可用图片"}</p>
          {editingItem?.unavailable_reason && <p className="mt-2 text-xs text-amber-800">{editingItem.unavailable_reason} · 此卡仅保留历史依据，请重新选择有效参考图。</p>}
          <div className="mt-3 grid gap-3 sm:grid-cols-[10rem_1fr]">
            <label className="text-xs text-gray-600">参考结论<select aria-label="参考结论" value={verdict} disabled={saving || !targetSample} onChange={(event) => { setVerdict(event.target.value as ReferenceVerdict); setDirty(true); }} className="mt-1 min-h-10 w-full rounded-lg border border-line bg-white px-2 text-sm">{Object.entries(VERDICT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="text-xs text-gray-600">判定依据（最多 500 字）<textarea aria-label="参考卡判定依据" value={note} maxLength={500} disabled={saving || !targetSample} onChange={(event) => { setNote(event.target.value); setDirty(true); }} rows={2} placeholder="例如：边缘浅划痕不影响使用，可接受；中央缺口不可接受。" className="mt-1 w-full resize-y rounded-lg border border-line bg-white p-2 text-sm" /></label>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2"><button type="button" disabled={saving || loading || !targetSample || !note.trim()} onClick={() => void saveCard()} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-gray-900 px-3 text-sm text-white disabled:opacity-40">{saving ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}保存参考卡</button>{editing && <button type="button" disabled={saving} onClick={() => requestAction(resetForm)} className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm">改用当前图片</button>}{dirty && <span className="text-xs text-amber-800">参考卡有未保存修改</span>}</div>
        </div>
        <div className="my-3 flex flex-wrap items-center justify-between gap-2"><label className="inline-flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={allCategories} onChange={(event) => setAllCategories(event.target.checked)} />显示此数据集全部类别</label><button type="button" disabled={saving || loading} onClick={() => requestAction(() => { resetForm(); setVersion((value) => value + 1); })} className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40"><RefreshCw size={13} />刷新参考卡</button></div>
        {loading ? <p role="status" className="py-10 text-center text-sm text-gray-500">正在加载参考卡…</p> : visibleCards.length === 0 ? <p className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-gray-500">该范围还没有参考卡。挑选典型边界图片，写下判定依据后保存。</p> : <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{visibleCards.map(({ collection, item }) => <article key={`${collection.id}:${item.sample_id}`} className="min-w-0 rounded-lg border border-line p-3">
          <button type="button" disabled={!item.sample || Boolean(item.unavailable_reason)} onClick={() => { setPreview(item.sample); setPreviewFailed(false); }} className="block h-36 w-full overflow-hidden rounded-lg bg-gray-100 disabled:cursor-default" aria-label={`查看参考原图：${item.sample?.filename ?? item.sample_id}`}><LocalBrowseThumbnail key={`${item.sample_id}:${item.file_hash}`} sampleId={item.sample?.id ?? null} name={item.sample?.filename ?? "样本记录已删除"} fileStatus={item.unavailable_reason ? "missing" : item.sample?.file_status} contentHash={item.file_hash} /></button>
          <div className="mt-2 flex flex-wrap items-center gap-2"><span className={`rounded border px-2 py-0.5 text-xs ${VERDICT_STYLES[item.verdict ?? "uncertain"]}`}>{VERDICT_LABELS[item.verdict ?? "uncertain"]}</span><span className="truncate text-[11px] text-gray-500" title={collection.name}>{collection.name}</span></div>
          <p className="mt-2 break-all text-xs font-medium text-gray-700">{item.sample?.filename ?? `样本 ${item.sample_id} · 记录已删除`}</p><p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-gray-600">{item.note || "未填写依据"}</p>
          {item.unavailable_reason && <p className="mt-2 text-xs text-amber-800">{item.unavailable_reason}</p>}
          <div className="mt-2 flex gap-3"><button type="button" disabled={saving || !item.sample || Boolean(item.unavailable_reason)} onClick={() => requestAction(() => { setEditing({ collectionId: collection.id, sampleId: item.sample_id }); setVerdict(item.verdict ?? "uncertain"); setNote(item.note); setDirty(false); setNotice(null); })} className="min-h-9 text-xs text-gray-600 underline underline-offset-2 disabled:opacity-40">编辑</button><button type="button" disabled={saving} onClick={() => requestAction(() => void removeCard(collection, item))} className="min-h-9 text-xs text-red-700 underline underline-offset-2 disabled:opacity-40">移除参考卡</button></div>
        </article>)}</div>}
      </div>
    </section>
    {preview && <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40 p-3" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreview(null); }}><section data-reference-preview="true" role="dialog" aria-modal="true" aria-label="参考原图" className="max-h-full w-full max-w-5xl overflow-auto rounded-xl bg-white p-3"><div className="mb-2 flex items-start justify-between gap-3"><p className="break-all text-xs text-gray-600">{preview.filename}</p><button autoFocus type="button" onClick={() => setPreview(null)} aria-label="关闭参考原图" className="rounded-lg p-2 hover:bg-gray-100"><X size={18} /></button></div>{previewFailed ? <p role="alert" className="p-10 text-center text-sm text-red-700">原图读取失败，请关闭后检查文件路径或重新扫描。</p> : <img src={getSampleFileUrl(preview.id)} alt={preview.filename} className="mx-auto max-h-[75vh] max-w-full object-contain" onError={() => setPreviewFailed(true)} />}</section></div>}
    {pendingAction && <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/30 p-4"><section data-reference-leave="true" role="dialog" aria-modal="true" aria-label="参考卡有未保存修改" className="w-full max-w-md rounded-xl bg-white p-5 shadow-lg"><h3 className="font-semibold">参考卡有未保存修改</h3><p className="mt-2 text-sm text-gray-600">保存成功后再继续，或放弃本次参考卡修改。</p>{error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}<div className="mt-4 flex flex-wrap gap-2"><button autoFocus type="button" disabled={saving || !targetSample || !note.trim()} onClick={() => void saveCard().then((saved) => { if (saved) { const action = pendingAction; setPendingAction(null); action(); } })} className="min-h-10 rounded-lg bg-gray-900 px-3 text-sm text-white disabled:opacity-40">{saving ? "正在保存…" : "保存并继续"}</button><button type="button" disabled={saving} onClick={() => { const action = pendingAction; resetForm(); setPendingAction(null); action(); }} className="min-h-10 rounded-lg border border-line px-3 text-sm disabled:opacity-40">放弃修改</button><button type="button" disabled={saving} onClick={() => setPendingAction(null)} className="min-h-10 rounded-lg border border-line px-3 text-sm disabled:opacity-40">取消</button></div></section></div>}
  </div>;
}
