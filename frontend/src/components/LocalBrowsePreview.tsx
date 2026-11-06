import { ChevronLeft, ChevronRight, Copy, ImageOff, Minus, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

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
  onClose: () => void;
  onNavigate: (offset: number) => void;
}

export default function LocalBrowsePreview({ sample, index, count, onClose, onNavigate }: Props) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [zoom, setZoom] = useState(1);
  const [failed, setFailed] = useState(false);
  const [dimensions, setDimensions] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const [showMask, setShowMask] = useState(false);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, []);

  useEffect(() => { setZoom(1); setFailed(false); setDimensions(null); setCopyStatus(""); setShowMask(false); }, [sample.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.target instanceof HTMLElement && event.target.closest("input, textarea, select, video, [contenteditable=true]")) return;
      if (event.key === "ArrowLeft" && index > 0) { event.preventDefault(); onNavigate(-1); }
      if (event.key === "ArrowRight" && index < count - 1) { event.preventDefault(); onNavigate(1); }
      if (event.key === "Tab") {
        const buttons = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], video[controls]') ?? []);
        const first = buttons[0]; const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [count, index, onClose, onNavigate]);

  async function copyPath() {
    try { await navigator.clipboard.writeText(sample.absolute_path); setCopyStatus("路径已复制"); }
    catch { setCopyStatus("无法自动复制，可选中下方路径复制"); }
  }

  const unavailable = failed || sample.file_status !== "normal";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-2 backdrop-blur-sm sm:p-5" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} className="flex max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-line bg-white shadow-soft">
        <div className="flex min-w-0 items-center gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0 flex-1"><h2 id={titleId} className="truncate text-sm font-semibold text-ink" title={sample.filename}>{sample.filename}</h2><p className="mt-0.5 text-xs text-gray-500">本页 {index + 1} / {count} · ← → 切换 · Esc 关闭</p></div>
          <button ref={closeButton} type="button" onClick={onClose} aria-label="关闭预览" className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"><X size={20} /></button>
        </div>
        <div className="relative min-h-0 bg-gray-100">
          {sample.file_type === "image" && !unavailable && !dimensions && <span role="status" className="pointer-events-none absolute left-3 top-3 rounded-lg bg-white/90 px-3 py-2 text-xs text-gray-500">正在加载原图…</span>}
          <div className="h-[min(60vh,600px)] min-h-40 overflow-auto" aria-label="文件预览">
            {unavailable ? <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center text-sm text-gray-500"><ImageOff size={38} className="text-gray-400" /><p>无法读取原文件，请在数据准备中检查路径或重新扫描。</p></div>
              : sample.file_type === "image" ? <div style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }} className="relative flex items-center justify-center">{sample.mask_path ? <BenchmarkImagePreview sampleId={sample.id} showMask={showMask} onDimensions={setDimensions} onFailed={setFailed} /> : <img key={sample.id} src={getSampleFileUrl(sample.id)} alt={sample.filename} className="h-full w-full object-contain" onError={() => setFailed(true)} onLoad={(event) => setDimensions(`${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight} px`)} />}</div>
              : sample.file_type === "video" ? <video key={sample.id} src={getSampleFileUrl(sample.id)} controls className="h-full w-full object-contain" onError={() => setFailed(true)} />
              : <div className="flex h-full items-center justify-center px-5 text-center text-sm text-gray-500">此类型暂不提供大图预览，可在数据准备中查看文件详情。</div>}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5">
          {sample.mask_path && <label className="inline-flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={showMask} onChange={(event) => setShowMask(event.target.checked)} className="accent-gray-900" />显示官方 Mask</label>}
          <div className="flex items-center gap-1"><button type="button" disabled={index === 0} onClick={() => onNavigate(-1)} aria-label="上一张" className="rounded-lg p-2 text-gray-600 hover:bg-gray-100 disabled:opacity-30"><ChevronLeft size={19} /></button><button type="button" disabled={index === count - 1} onClick={() => onNavigate(1)} aria-label="下一张" className="rounded-lg p-2 text-gray-600 hover:bg-gray-100 disabled:opacity-30"><ChevronRight size={19} /></button><span className="ml-1 text-xs text-gray-500">{dimensions ? `${dimensions} · ` : ""}{browseFileSize(sample.file_size)}</span></div>
          {sample.file_type === "image" && !unavailable && <div className="flex items-center gap-1"><button type="button" disabled={zoom <= 1} onClick={() => setZoom((value) => Math.max(1, value - 0.5))} aria-label="缩小图片" className="rounded-lg p-2 text-gray-600 hover:bg-gray-100 disabled:opacity-30"><Minus size={17} /></button><button type="button" onClick={() => setZoom(1)} className="rounded-lg px-2 py-1 text-xs text-gray-600 hover:bg-gray-100">{zoom === 1 ? "适应窗口" : `${zoom.toFixed(1)} 倍 · 还原`}</button><button type="button" disabled={zoom >= 4} onClick={() => setZoom((value) => Math.min(4, value + 0.5))} aria-label="放大图片" className="rounded-lg p-2 text-gray-600 hover:bg-gray-100 disabled:opacity-30"><Plus size={17} /></button></div>}
        </div>
        <div className="border-t border-line px-4 py-3"><div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500"><span>{sample.file_status === "normal" ? "文件可用" : sample.file_status === "missing" ? "文件缺失" : "文件不可用"}</span><button type="button" onClick={() => void copyPath()} className="inline-flex items-center gap-1 underline underline-offset-2"><Copy size={12} />复制原始路径</button><span role="status">{copyStatus}</span></div><p className="mt-1.5 select-text break-all text-xs leading-5 text-gray-600">{sample.absolute_path}</p></div>
      </div>
    </div>
  );
}
