import { ChevronLeft, ChevronRight, ImageOff, Loader2, RefreshCw, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type UIEvent } from "react";

import { getSampleFileUrl } from "../api/client";
import { organizationError } from "../api/organization";
import { getWorkpieceViews } from "../api/workpiece";
import type { Sample } from "../types/dataset";
import type { WorkpieceViews } from "../types/workpiece";
import { okGradeCopy } from "../utils/uiCopy";
import LocalBrowseThumbnail from "./LocalBrowseThumbnail";
import Modal from "./Modal";

interface Props {
  sampleId: number;
  onClose: () => void;
}

const buttonClass = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-default disabled:opacity-40";

function judgment(sample: Sample): string {
  if (sample.triage_status === "ng") return "NG 异常";
  if (sample.triage_status === "pending") return "待定复看";
  if (sample.triage_status === "untriaged") return "未分拣";
  if (sample.ok_grade === "clear") return okGradeCopy.clear;
  if (sample.ok_grade === "borderline") return okGradeCopy.borderline;
  return "OK（未细分等级）";
}

function statusStyle(sample: Sample): string {
  if (sample.triage_status === "ng") return "border-red-200 bg-red-50 text-red-800";
  if (sample.triage_status === "pending" || sample.triage_outdated) return "border-amber-200 bg-amber-50 text-amber-900";
  if (sample.triage_status === "ok") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  return "border-line bg-gray-50 text-gray-600";
}

function ViewImage({ sample }: { sample: Sample }) {
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [retry, setRetry] = useState(0);
  if (failed) return <div role="alert" className="flex h-full min-h-48 flex-col items-center justify-center gap-3 p-4 text-center text-sm text-gray-600"><ImageOff size={30} /><p>原图暂时无法读取，请确认本地文件可访问。</p><button type="button" className={buttonClass} onClick={() => { setFailed(false); setReady(false); setRetry(value => value + 1); }}>重新读取原图</button></div>;
  return <div className="relative h-full w-full">
    <img key={retry} src={getSampleFileUrl(sample.id)} alt={`工件视角 ${sample.relative_path}`} draggable={false} onLoad={() => setReady(true)} onError={() => setFailed(true)} className="h-full w-full max-w-none select-none object-contain" />
    {!ready && <span role="status" className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 text-sm text-gray-500"><Loader2 size={18} className="animate-spin" />正在读取原图…</span>}
  </div>;
}

export default function WorkpieceViewsPanel(props: Props) {
  return <WorkpieceViewsContent key={props.sampleId} {...props} />;
}

function WorkpieceViewsContent({ sampleId, onClose }: Props) {
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [response, setResponse] = useState<{ key: string; data: WorkpieceViews } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [selection, setSelection] = useState<{ key: string; ids: number[] }>({ key: "", ids: [] });
  const [zoom, setZoom] = useState(1);
  const [syncEnabled, setSyncEnabled] = useState(true);
  const requestKey = `${sampleId}:${page}:${refresh}`;
  const data = response?.key === requestKey ? response.data : null;
  const error = failure?.key === requestKey ? failure.message : null;
  const loading = !data && !error;
  const selectedIds = selection.key === requestKey ? selection.ids : [];
  const selected = data?.items.filter(item => selectedIds.includes(item.id)) ?? [];
  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const root = useRef<HTMLDivElement>(null);
  const viewports = useRef(new Map<number, HTMLDivElement>());
  const pendingScroll = useRef(new Map<number, { left: number; top: number }>());
  const pan = useRef({ x: 0, y: 0 });
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void getWorkpieceViews(sampleId, page, controller.signal).then(value => {
      if (!active) return;
      setResponse({ key: requestKey, data: value });
      const ordered = [...value.items].sort((a, b) => Number(b.id === sampleId) - Number(a.id === sampleId));
      setSelection({ key: requestKey, ids: ordered.slice(0, 4).map(item => item.id) });
    }).catch((cause: unknown) => {
      if (active && !controller.signal.aborted) setFailure({ key: requestKey, message: organizationError(cause, "工件视角读取失败，请重试。") });
    });
    return () => { active = false; controller.abort(); };
  }, [sampleId, page, requestKey]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    root.current?.querySelector<HTMLButtonElement>("button")?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const elements = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]') ?? []);
      const first = elements[0]; const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previousOverflow; previousFocus?.focus(); window.removeEventListener("keydown", onKey); };
  }, []);

  function resetPan() {
    pan.current = { x: 0, y: 0 };
    pendingScroll.current.clear();
    for (const viewport of viewports.current.values()) viewport.scrollTo(0, 0);
  }

  function syncPan(sample: number, event: UIEvent<HTMLDivElement>) {
    if (!syncEnabled) return;
    const origin = event.currentTarget;
    const expected = pendingScroll.current.get(sample);
    if (expected && Math.abs(origin.scrollLeft - expected.left) < 1 && Math.abs(origin.scrollTop - expected.top) < 1) { pendingScroll.current.delete(sample); return; }
    pendingScroll.current.delete(sample);
    pan.current = { x: origin.scrollLeft / Math.max(1, origin.scrollWidth - origin.clientWidth), y: origin.scrollTop / Math.max(1, origin.scrollHeight - origin.clientHeight) };
    for (const [id, target] of viewports.current) {
      if (id === sample) continue;
      const left = pan.current.x * Math.max(0, target.scrollWidth - target.clientWidth);
      const top = pan.current.y * Math.max(0, target.scrollHeight - target.clientHeight);
      if (Math.abs(target.scrollLeft - left) < 1 && Math.abs(target.scrollTop - top) < 1) continue;
      pendingScroll.current.set(id, { left, top });
      target.scrollTo(left, top);
    }
  }

  useLayoutEffect(() => { resetPan(); }, [requestKey]);
  useLayoutEffect(() => {
    for (const [id, viewport] of viewports.current) {
      const left = pan.current.x * Math.max(0, viewport.scrollWidth - viewport.clientWidth);
      const top = pan.current.y * Math.max(0, viewport.scrollHeight - viewport.clientHeight);
      pendingScroll.current.set(id, { left, top });
      viewport.scrollTo(left, top);
    }
  }, [zoom, selectedIds.join(","), syncEnabled]);

  function choose(id: number) {
    setSelection(value => {
      const ids = value.key === requestKey ? value.ids : [];
      return { key: requestKey, ids: ids.includes(id) ? ids.filter(item => item !== id) : ids.length < 4 ? [...ids, id] : ids };
    });
  }

  return <div ref={root}><Modal open title="工件多视角" onClose={onClose} size="xl">
    <div className="min-w-0 space-y-4 p-3 sm:p-5">
      <p className="text-sm leading-6 text-gray-600">只读查看同一采集批次、同一工件的图片；在这里切换视角不会切换主分拣图片或修改判定。</p>
      {loading && <p role="status" className="flex items-center gap-2 py-6 text-sm text-gray-500"><Loader2 size={18} className="animate-spin" />正在读取工件视角…</p>}
      {error && <div role="alert" className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><p>{error}</p><button type="button" className={buttonClass} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={15} />重试读取</button></div>}
      {data && <>
        <div className="space-y-2 rounded-lg border border-line bg-gray-50 p-3 text-sm">
          <p className="break-all">工件：{data.capture_group_id || "未登记"} · 批次：{data.capture_batch_id || "未登记"} · 工件视角 {data.total} 张</p>
          {!data.capture_group_id && <p className="text-amber-800">当前图片未登记工件组，仅显示本张。请回数据准备登记分组后再查看多视角。</p>}
          <p className={data.isolation.normal_candidate ? "font-medium text-emerald-800" : "font-medium text-amber-900"}>训练隔离组 {data.isolation.total} 张：{data.isolation.normal_candidate ? "满足登记态纯正常候选条件" : "尚不满足纯正常候选条件"}</p>
          {Object.entries(data.isolation.reasons).length > 0 && <ul className="list-inside list-disc space-y-1 text-xs text-gray-600">{Object.entries(data.isolation.reasons).map(([reason, count]) => <li key={reason}>{reason}：{count} 张</li>)}</ul>}
          <p className="text-xs leading-5 text-gray-500">相同内容可能连接其他工件，使训练隔离组大于当前工件视图；原因涉及图片可重叠。此处按登记信息判断，正式预检仍核对原图、范围和划分。</p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-gray-600">勾选本页最多 4 个视角同屏查看；翻页后重新选择。</p>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" aria-label="缩小所有视角" className={buttonClass} disabled={zoom <= 1} onClick={() => setZoom(value => Math.max(1, value - 0.5))}><ZoomOut size={16} /></button>
            <span className="min-w-10 text-center text-sm tabular-nums">{Math.round(zoom * 100)}%</span>
            <button type="button" aria-label="放大所有视角" className={buttonClass} disabled={zoom >= 4} onClick={() => setZoom(value => Math.min(4, value + 0.5))}><ZoomIn size={16} /></button>
            <button type="button" className={buttonClass} onClick={() => { setZoom(1); resetPan(); }}><RotateCcw size={14} />还原</button>
            <label className="inline-flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={syncEnabled} onChange={event => setSyncEnabled(event.target.checked)} />同步位置</label>
          </div>
        </div>
        <div className="grid max-h-44 min-w-0 grid-cols-2 gap-2 overflow-y-auto sm:grid-cols-4" aria-label="选择工件视角">
          {data.items.map(item => <label key={`${item.id}:${item.file_hash}`} className={`min-w-0 cursor-pointer rounded-lg border p-2 ${selectedIds.includes(item.id) ? "border-gray-900 bg-gray-50" : "border-line"}`}>
            <div className="mb-2 flex min-w-0 items-start gap-2"><input type="checkbox" aria-label={`查看视角 ${item.relative_path}`} checked={selectedIds.includes(item.id)} disabled={!selectedIds.includes(item.id) && selectedIds.length >= 4} onChange={() => choose(item.id)} /><span className="min-w-0 break-all text-xs" title={item.relative_path}>{item.filename}{item.id === sampleId ? " · 当前图片" : ""}</span></div>
            <div className="h-16 overflow-hidden rounded bg-gray-50"><LocalBrowseThumbnail key={`${item.id}:${item.file_hash}:${refresh}`} sampleId={item.id} name={item.filename} fileStatus={item.file_status} contentHash={item.file_hash} /></div>
            <p className="mt-2 break-words text-xs text-gray-600">{judgment(item)}{item.triage_outdated ? " · 判定已过期" : ""}{item.file_status !== "normal" ? " · 文件不可用" : ""}</p>
          </label>)}
        </div>
        <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2" aria-label="工件视角大图">
          {selected.map(item => <section key={`${item.id}:${item.file_hash}`} className="min-w-0 overflow-hidden rounded-lg border border-line">
            <div className="space-y-1 border-b border-line p-3"><p className="break-all text-sm font-medium">{item.relative_path}</p><div className="flex flex-wrap gap-1.5 text-xs"><span className={`rounded border px-2 py-1 ${statusStyle(item)}`}>{judgment(item)}</span>{item.triage_outdated && <span className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-900">判定已过期，需复核</span>}{item.file_status !== "normal" && <span className="rounded border border-red-200 bg-red-50 px-2 py-1 text-red-800">文件不可用 · {item.file_status}</span>}</div></div>
            <div ref={element => { if (element) viewports.current.set(item.id, element); else { viewports.current.delete(item.id); pendingScroll.current.delete(item.id); } }} role="region" aria-label={`视角大图 ${item.relative_path}`} tabIndex={0} onScroll={event => syncPan(item.id, event)} className="h-64 overflow-auto bg-gray-50 outline-offset-[-2px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-gray-800 sm:h-80">
              <div style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }} className="min-h-full min-w-full"><ViewImage key={`${item.id}:${item.file_hash}:${refresh}`} sample={item} /></div>
            </div>
          </section>)}
        </div>
        {selected.length === 0 && <p className="rounded-lg bg-gray-50 p-5 text-center text-sm text-gray-500">请勾选至少一个视角查看原图。</p>}
        <p className="text-xs text-gray-500">所有视角共用缩放比例，滚动时按相对位置同步；不进行图像配准。</p>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          <span className="text-xs text-gray-500">第 {data.page} / {pageCount} 页 · 共 {data.total} 张</span>
          <div className="flex flex-wrap gap-2"><button type="button" className={buttonClass} disabled={data.page <= 1} onClick={() => setPage(data.page - 1)}><ChevronLeft size={14} />上一页</button><button type="button" className={buttonClass} disabled={data.page >= pageCount} onClick={() => setPage(data.page + 1)}>下一页<ChevronRight size={14} /></button><button type="button" className={buttonClass} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={14} />刷新</button></div>
        </div>
      </>}
    </div>
  </Modal></div>;
}
