import { ChevronLeft, ChevronRight, Copy, ImageOff, Loader2, Minus, Plus, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { PointerEvent } from "react";

import { getSampleFileUrl } from "../api/client";
import type { Sample } from "../types/dataset";
import BenchmarkImagePreview from "./BenchmarkImagePreview";

export function browseFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

interface Props {
  sample: Sample;
  index: number;
  count: number;
  navigationLoading?: boolean;
  navigationError?: string;
  onClose: () => void;
  onNavigate: (offset: number) => void;
}

interface ImageDimensions { width: number; height: number }

const controlStyle = "rounded-lg px-2 py-1.5 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-30";

export default function LocalBrowsePreview({ sample, index, count, navigationLoading = false, navigationError, onClose, onNavigate }: Props) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ pointerId: number; x: number; y: number; left: number; top: number } | null>(null);
  const [mode, setMode] = useState<"fit" | "pixels">("fit");
  const [zoom, setZoom] = useState(1);
  const [imageState, setImageState] = useState<{ sampleId: number; failed: boolean; dimensions: ImageDimensions | null }>({ sampleId: sample.id, failed: false, dimensions: null });
  const failed = imageState.sampleId === sample.id && imageState.failed;
  const dimensions = imageState.sampleId === sample.id ? imageState.dimensions : null;
  const [copyStatus, setCopyStatus] = useState("");
  const [showMask, setShowMask] = useState(false);
  const activeSample = useRef(sample.id);
  activeSample.current = sample.id;
  const reportDimensions = useCallback((value: ImageDimensions) => {
    if (activeSample.current === sample.id) setImageState({ sampleId: sample.id, failed: false, dimensions: value });
  }, [sample.id]);
  const reportFailure = useCallback((value: boolean) => {
    if (activeSample.current !== sample.id) return;
    setImageState((current) => ({ sampleId: sample.id, failed: value, dimensions: current.sampleId === sample.id ? current.dimensions : null }));
  }, [sample.id]);
  const readDimensions = useCallback((value: string) => {
    const match = /^(\d+) × (\d+)/.exec(value);
    if (match) reportDimensions({ width: Number(match[1]), height: Number(match[2]) });
  }, [reportDimensions]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    setCopyStatus(""); setShowMask(false);
    drag.current = null;
    viewport.current?.scrollTo({ left: 0, top: 0 });
  }, [sample.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.target instanceof HTMLElement && event.target.closest("input, textarea, select, video, [contenteditable=true]")) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        if (navigationLoading) return;
        if (event.key === "ArrowLeft" && index > 0) onNavigate(-1);
        if (event.key === "ArrowRight" && index < count - 1) onNavigate(1);
      }
      if (event.key === "Tab") {
        const buttons = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href], video[controls], [tabindex="0"]') ?? []);
        const first = buttons[0]; const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [count, index, navigationLoading, onClose, onNavigate]);

  async function copyPath() {
    const id = sample.id;
    try { await navigator.clipboard.writeText(sample.absolute_path); if (id === activeSample.current) setCopyStatus("路径已复制"); }
    catch { if (id === activeSample.current) setCopyStatus("无法自动复制，可选中下方路径复制"); }
  }

  function beginDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType !== "mouse" || event.button !== 0 || !dimensions || (mode === "fit" && zoom === 1)) return;
    const target = event.currentTarget;
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: target.scrollLeft, top: target.scrollTop };
    target.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    event.currentTarget.scrollLeft = drag.current.left - (event.clientX - drag.current.x);
    event.currentTarget.scrollTop = drag.current.top - (event.clientY - drag.current.y);
  }

  function endDrag(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  const unavailable = failed || sample.file_status !== "normal";
  const pixels = mode === "pixels" && dimensions;
  const imageWidth = pixels ? dimensions.width * zoom : "100%";
  const imageHeight = pixels ? dimensions.height * zoom : "100%";
  const canDrag = !unavailable && sample.file_type === "image" && (mode === "pixels" || zoom > 1);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-2 backdrop-blur-sm sm:p-5" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} className="flex h-[min(92vh,900px)] max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-line bg-white shadow-soft">
        <div className="flex min-w-0 items-center gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0 flex-1"><h2 id={titleId} className="truncate text-sm font-semibold text-ink" title={sample.filename}>{sample.filename}</h2><p className="mt-0.5 text-xs text-gray-500">当前范围 {index + 1} / {count} · ← → 连续切换 · Esc 关闭</p></div>
          <button ref={closeButton} type="button" onClick={onClose} aria-label="关闭预览" className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"><X size={20} /></button>
        </div>
        <div className="relative min-h-0 flex-1 bg-gray-100">
          {sample.file_type === "image" && !unavailable && !dimensions && <span role="status" className="pointer-events-none absolute left-3 top-3 z-10 rounded-lg bg-white/90 px-3 py-2 text-xs text-gray-500">正在加载原图…</span>}
          {navigationLoading && <span role="status" className="pointer-events-none absolute right-3 top-3 z-10 inline-flex items-center gap-2 rounded-lg bg-white/95 px-3 py-2 text-xs text-gray-600"><Loader2 size={14} className="animate-spin" />正在加载相邻图片…</span>}
          <div ref={viewport} tabIndex={0} onPointerDown={beginDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={() => { drag.current = null; }} className={`h-full overflow-auto outline-offset-[-2px] ${canDrag ? "cursor-grab active:cursor-grabbing" : ""}`} aria-label="文件预览，可滚动或拖动查看细节">
            {unavailable ? <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center text-sm text-gray-500"><ImageOff size={38} className="text-gray-400" /><p>无法读取原文件，请在数据准备中检查路径或重新扫描。</p></div>
              : sample.file_type === "image" ? <div style={{ width: pixels ? imageWidth : `${zoom * 100}%`, height: pixels ? imageHeight : `${zoom * 100}%` }} className="grid min-h-full min-w-full place-items-center"><div style={{ width: imageWidth, height: imageHeight }} className="relative flex min-h-0 min-w-0 items-center justify-center">{sample.mask_path ? <BenchmarkImagePreview key={sample.id} sampleId={sample.id} showMask={showMask} onDimensions={readDimensions} onFailed={reportFailure} /> : <img key={sample.id} src={getSampleFileUrl(sample.id)} alt={sample.filename} draggable={false} className="h-full w-full max-w-none select-none object-contain" onError={() => reportFailure(true)} onLoad={(event) => reportDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />}</div></div>
              : sample.file_type === "video" ? <video key={sample.id} src={getSampleFileUrl(sample.id)} controls className="h-full w-full object-contain" onError={() => reportFailure(true)} />
              : <div className="flex h-full items-center justify-center px-5 text-center text-sm text-gray-500">此类型暂不提供大图预览，可在数据准备中查看文件详情。</div>}
          </div>
        </div>
        {navigationError && <p role="alert" className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs leading-5 text-amber-800">{navigationError}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5">
          {sample.mask_path && <label className="inline-flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={showMask} onChange={(event) => setShowMask(event.target.checked)} className="accent-gray-900" />显示官方 Mask</label>}
          <div className="flex items-center gap-1"><button type="button" disabled={navigationLoading || index === 0} onClick={() => onNavigate(-1)} aria-label="上一张" className="rounded-lg p-2 text-gray-600 hover:bg-gray-100 disabled:opacity-30"><ChevronLeft size={19} /></button><button type="button" disabled={navigationLoading || index >= count - 1} onClick={() => onNavigate(1)} aria-label="下一张" className="rounded-lg p-2 text-gray-600 hover:bg-gray-100 disabled:opacity-30"><ChevronRight size={19} /></button><span className="ml-1 text-xs text-gray-500">{dimensions ? `${dimensions.width} × ${dimensions.height} px · ` : ""}{browseFileSize(sample.file_size)}</span></div>
          {sample.file_type === "image" && !unavailable && <div className="flex flex-wrap items-center gap-1"><button type="button" aria-pressed={mode === "fit" && zoom === 1} onClick={() => { setMode("fit"); setZoom(1); }} className={`${controlStyle} ${mode === "fit" ? "bg-gray-100" : ""}`}>适应窗口</button><button type="button" aria-label="1:1 原始像素" aria-pressed={mode === "pixels" && zoom === 1} onClick={() => { setMode("pixels"); setZoom(1); }} className={`${controlStyle} ${mode === "pixels" ? "bg-gray-100" : ""}`}>1:1 原始像素</button><button type="button" disabled={zoom <= (mode === "pixels" ? 0.25 : 1)} onClick={() => setZoom((value) => Math.max(mode === "pixels" ? 0.25 : 1, value - 0.25))} aria-label="缩小图片" className={controlStyle}><Minus size={17} /></button><span className="min-w-12 text-center text-xs tabular-nums text-gray-500" aria-label="当前缩放">{mode === "pixels" ? `${Math.round(zoom * 100)}%` : `${zoom.toFixed(2)} 倍`}</span><button type="button" disabled={zoom >= 4} onClick={() => setZoom((value) => Math.min(4, value + 0.25))} aria-label="放大图片" className={controlStyle}><Plus size={17} /></button></div>}
        </div>
        <div className="border-t border-line px-4 py-3"><div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500"><span>{sample.file_status === "normal" ? "文件可用" : sample.file_status === "missing" ? "文件缺失" : "文件不可用"}</span>{canDrag && <span>拖动或滚动查看细节 · 切图保留缩放模式</span>}<button type="button" onClick={() => void copyPath()} className="inline-flex items-center gap-1 underline underline-offset-2"><Copy size={12} />复制原始路径</button><span role="status">{copyStatus}</span></div><p className="mt-1.5 select-text break-all text-xs leading-5 text-gray-600">{sample.absolute_path}</p></div>
      </div>
    </div>
  );
}
