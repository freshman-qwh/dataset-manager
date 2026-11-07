import { useEffect, useRef, useState } from "react";
import { getLookupCandidates, lookupFilenames } from "../api/dailyTools";
import type { FilenameLookupRead, FilenameLookupResult } from "../types/dailyTools";
import LocalBrowseThumbnail from "./LocalBrowseThumbnail";
import Modal from "./Modal";

interface Props { open: boolean; datasetId: number; onClose: () => void; onSelect: (sampleIds: number[]) => void }
const button = "min-h-10 rounded-lg border border-line px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40";

export default function FilenameLookupModal({ open, datasetId, onClose, onSelect }: Props) {
  const [text, setText] = useState("");
  const [data, setData] = useState<FilenameLookupRead | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [paging, setPaging] = useState<string | null>(null);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;

  useEffect(() => {
    request.current?.abort(); setData(null); setSelected([]); setLoading(false); setPaging(null); setError("");
    return () => { request.current?.abort(); };
  }, [open, datasetId]);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow; document.body.style.overflow = "hidden"; textarea.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key !== "Tab") return;
      const dialog = container.current?.closest('[role="dialog"]');
      const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea') ?? []);
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls[controls.length - 1]?.focus(); }
      if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) { event.preventDefault(); controls[0]?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = overflow; previous?.focus(); };
  }, [open]);

  async function find() {
    const entries = text.split(/\r?\n/).filter((line) => line.trim());
    if (!entries.length || entries.length > 500) { setError("请输入 1–500 行文件名或路径，每行一项。"); return; }
    if (entries.some((line) => line.length > 2000)) { setError("单行路径过长，请检查输入。"); return; }
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setPaging(null); setError(""); setData(null); setSelected([]);
    try { const result = await lookupFilenames(datasetId, entries, controller.signal); if (!controller.signal.aborted) setData(result); }
    catch { if (!controller.signal.aborted) setError("查找失败，请检查服务并重试。"); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }
  async function page(result: FilenameLookupResult, offset: number) {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setPaging(result.entry); setError("");
    try {
      const next = await getLookupCandidates(datasetId, result.entry, result.page + offset, controller.signal);
      if (!controller.signal.aborted) setData((current) => current?.dataset_id === datasetId ? { ...current, results: current.results.map((row) => row.entry === result.entry ? next : row) } : current);
    } catch { if (!controller.signal.aborted) setError("候选加载失败，请重试。"); }
    finally { if (!controller.signal.aborted) setPaging(null); }
  }
  const current = data?.dataset_id === datasetId ? data : null;
  const matched = current?.results.filter((row) => row.total > 0).length ?? 0;
  function selectUniqueMatches() {
    if (!current) return;
    const merged = Array.from(new Set([...selected, ...current.results.filter((row) => row.total === 1)
      .flatMap((row) => row.candidates.filter((item) => item.file_status === "normal").map((item) => item.id))]));
    if (merged.length > 100) {
      setError(`唯一匹配项合并后共 ${merged.length} 张，超过单次 100 张上限。已保留原选择，请手动分批选择。`);
      return;
    }
    setError(""); setSelected(merged);
  }

  return <Modal open={open} title="粘贴清单找图" onClose={onClose} size="xl"><div ref={container} className="space-y-4 p-3 sm:p-5">
    <p className="text-xs leading-5 text-gray-500">在当前数据集的已登记图片中精确匹配文件名、相对路径或绝对路径，每行一项，最多 500 行。重名时请核对来源路径后勾选。每个收集篮最多 100 张，单次最多选择 100 张。</p>
    <label className="block text-sm text-gray-600">文件名或路径清单<textarea ref={textarea} aria-label="文件名或路径清单" value={text} onChange={(event) => setText(event.target.value)} rows={5} placeholder={'part-001.png\nimages/part-002.png'} className="mt-2 block w-full rounded-lg border border-line p-3 font-mono text-xs outline-none focus:border-gray-500" /></label>
    <div className="flex flex-wrap items-center gap-2"><button type="button" disabled={loading || !text.trim()} onClick={() => void find()} className={button}>{loading ? "正在查找…" : "查找图片"}</button>{current && <><span role="status" className="text-xs text-gray-500">{matched} / {current.results.length} 项找到图片 · 已忽略 {current.duplicate_count} 项重复输入</span><button type="button" disabled={loading || paging !== null} onClick={selectUniqueMatches} className={button}>勾选唯一匹配项</button></>}</div>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {current && <div className="max-h-[45vh] space-y-3 overflow-y-auto">{current.results.map((row) => <section key={row.entry} className="rounded-lg border border-line p-3"><div className="flex flex-wrap items-start justify-between gap-2"><p className="min-w-0 break-all text-sm font-medium text-gray-700">{row.entry}</p><span className={`text-xs ${row.total === 0 ? "text-red-700" : row.total > 1 ? "text-amber-800" : "text-gray-500"}`}>{row.total === 0 ? "未找到" : row.total > 1 ? `${row.total} 个重名候选，请手动选择` : "唯一匹配"}</span></div>
      {row.candidates.map((sample) => <label key={sample.id} className="mt-2 flex min-w-0 items-center gap-3 rounded-md bg-gray-50 p-2"><input type="checkbox" aria-label={`选择 ${sample.absolute_path}`} checked={selected.includes(sample.id)} disabled={sample.file_status !== "normal" || (!selected.includes(sample.id) && selected.length >= 100)} onChange={() => setSelected((old) => old.includes(sample.id) ? old.filter((id) => id !== sample.id) : old.length < 100 ? [...old, sample.id] : old)} className="shrink-0 accent-gray-900 disabled:cursor-not-allowed" /><span className="h-12 w-14 shrink-0"><LocalBrowseThumbnail key={`${sample.id}:${sample.file_hash}`} sampleId={sample.id} name={sample.filename} contentHash={sample.file_hash} fileStatus={sample.file_status} /></span><span className="min-w-0"><span className="block break-all text-xs text-gray-600">{sample.absolute_path}</span>{sample.file_status !== "normal" && <span className="mt-1 block text-xs text-amber-800">文件当前不可用，请修复文件后再加入</span>}</span></label>)}
      {row.total > row.page_size && <div className="mt-2 flex flex-wrap items-center justify-end gap-2 text-xs text-gray-500"><button type="button" disabled={paging !== null || row.page <= 1} onClick={() => void page(row, -1)} className={button}>上一组候选</button><span>{row.page} / {Math.ceil(row.total / row.page_size)}</span><button type="button" disabled={paging !== null || row.page * row.page_size >= row.total} onClick={() => void page(row, 1)} className={button}>下一组候选</button></div>}
    </section>)}</div>}
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3"><span className="text-xs text-gray-500">已选择 {selected.length} / 100 张图片{selected.length === 100 && "，已达上限，可取消勾选后更换"}</span><button type="button" disabled={!selected.length || selected.length > 100 || loading || paging !== null} onClick={() => onSelect(selected)} className="min-h-10 rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40">将所选图片加入收集篮</button></div>
  </div></Modal>;
}
