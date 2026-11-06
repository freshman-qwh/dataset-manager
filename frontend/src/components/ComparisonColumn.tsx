import { ChevronLeft, ChevronRight, ImageOff, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, RefObject, UIEventHandler } from "react";

import BenchmarkImagePreview from "./BenchmarkImagePreview";
import LocalBrowseThumbnail from "./LocalBrowseThumbnail";
import { createThumbnailJob, getJob } from "../api/client";
import type { ComparisonSide, ComparisonSideName } from "../types/comparison";
import type { Sample } from "../types/dataset";

const buttonStyle = "inline-flex min-h-10 items-center justify-center gap-1 rounded-lg border border-line bg-white px-2.5 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:cursor-default disabled:opacity-35";

interface Props {
  side: ComparisonSideName;
  data: ComparisonSide | null;
  loading: boolean;
  zoom: number;
  viewportRef: RefObject<HTMLDivElement>;
  onScroll: UIEventHandler<HTMLDivElement>;
  onPageChange: (page: number) => void;
  onSampleChange: () => void;
}

function ComparisonImage({ sample, showMask }: { sample: Sample; showMask: boolean }) {
  const [failed, setFailed] = useState(false);
  const [dimensions, setDimensions] = useState("");
  const [retry, setRetry] = useState(0);
  if (failed) return <div role="alert" className="flex h-full min-h-40 flex-col items-center justify-center gap-3 p-5 text-center text-sm text-gray-500"><ImageOff size={32} /><p>原图暂时无法读取，请确认本地文件仍可访问。</p><button type="button" className={buttonStyle} onClick={() => { setFailed(false); setDimensions(""); setRetry((value) => value + 1); }}>重新读取</button></div>;
  return <div className="relative h-full w-full" title={dimensions || undefined}><BenchmarkImagePreview key={retry} sampleId={sample.id} showMask={showMask} onDimensions={setDimensions} onFailed={setFailed} />{!dimensions && <span role="status" className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 text-sm text-gray-500"><Loader2 size={18} className="animate-spin" />正在读取原图…</span>}</div>;
}

export default function ComparisonColumn({ side, data, loading, zoom, viewportRef, onScroll, onPageChange, onSampleChange }: Props) {
  const normal = side === "normal";
  const title = normal ? "正常参考" : "缺陷样本";
  const items = data?.items ?? [];
  const itemsKey = items.map((sample) => `${sample.id}:${sample.file_hash}`).join(",");
  const [selection, setSelection] = useState({ key: "", index: 0 });
  const index = selection.key === itemsKey ? Math.min(selection.index, Math.max(0, items.length - 1)) : 0;
  const sample = items[index];
  const [maskEnabled, setMaskEnabled] = useState(false);
  const [thumbnailReadyKey, setThumbnailReadyKey] = useState("");
  const drag = useRef<{ pointerId: number; x: number; y: number; left: number; top: number } | null>(null);
  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const datasetId = items[0]?.dataset_id;

  useEffect(() => {
    if (!datasetId || !items.length) return;
    let active = true;
    let timer: number | undefined;
    let polls = 0;
    const sampleIds = items.slice(0, 8).map((item) => item.id);
    const deadline = window.setTimeout(finish, 15000);
    function finish() {
      if (!active) return;
      setThumbnailReadyKey(itemsKey);
      active = false;
      window.clearTimeout(deadline);
      if (timer !== undefined) window.clearTimeout(timer);
    }
    async function poll(jobId: number) {
      try {
        const job = await getJob(jobId);
        if (!active) return;
        polls += 1;
        if ((job.status === "queued" || job.status === "running") && polls < 20) timer = window.setTimeout(() => void poll(jobId), 750);
        else finish();
      } catch { finish(); }
    }
    void createThumbnailJob(datasetId, sampleIds).then((result) => {
      if (!active) return;
      if (result.job) {
        window.dispatchEvent(new Event("dataset-manager:jobs-changed"));
        void poll(result.job.id);
      } else finish();
    }).catch(finish);
    return () => { active = false; window.clearTimeout(deadline); if (timer !== undefined) window.clearTimeout(timer); };
  }, [datasetId, itemsKey]);

  function choose(next: number) {
    if (next < 0 || next >= items.length || next === index) return;
    setSelection({ key: itemsKey, index: next });
    onSampleChange();
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.nativeEvent.isComposing) return;
    if ((event.target as HTMLElement).closest("input, textarea, select, button, a, [contenteditable=true]")) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      choose(index + (event.key === "ArrowLeft" ? -1 : 1));
    }
  }

  function beginDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType !== "mouse" || event.button !== 0 || zoom <= 1 || !sample || (event.target as HTMLElement).closest("button")) return;
    const viewport = event.currentTarget;
    viewport.focus({ preventScroll: true });
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
    viewport.setPointerCapture(event.pointerId);
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

  return <section aria-label={title} className="min-w-0 overflow-hidden rounded-xl border border-line bg-white" onKeyDown={onKeyDown}>
    <div className="flex min-h-16 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-line px-4 py-3">
      <h2 className="flex items-center gap-2 font-medium text-gray-800"><span className={`h-2 w-2 rounded-full ${normal ? "bg-emerald-500" : "bg-rose-500"}`} />{title}<span className="text-sm font-normal text-gray-500">{data ? `${data.total.toLocaleString()} 张` : ""}</span></h2>
      {!normal && <label className={`flex min-h-8 items-center gap-2 text-sm ${sample?.mask_path ? "text-gray-600" : "text-gray-400"}`} title={sample?.mask_path ? "红色显示已有 Mask，原图不变" : "当前样本没有 Mask"}><input type="checkbox" checked={maskEnabled && Boolean(sample?.mask_path)} disabled={!sample?.mask_path || loading} onChange={(event) => setMaskEnabled(event.target.checked)} className="h-4 w-4 accent-gray-800" />显示 Mask</label>}
    </div>

    <div ref={viewportRef} tabIndex={sample ? 0 : -1} role="region" aria-label={`${title}大图，左右方向键切换本页图片`} onScroll={onScroll} onPointerDown={beginDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={() => { drag.current = null; }} className={`h-72 overflow-auto bg-gray-50 outline-offset-[-2px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-gray-800 sm:h-96 xl:h-[28rem] ${zoom > 1 && sample ? "cursor-grab active:cursor-grabbing" : ""}`}>
      {loading ? <div role="status" className="flex h-full items-center justify-center gap-2 text-sm text-gray-500"><Loader2 size={18} className="animate-spin" />正在加载{title}…</div> : sample ? <div style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }} className="relative min-h-full min-w-full"><ComparisonImage key={`${sample.id}:${sample.file_hash}`} sample={sample} showMask={!normal && maskEnabled && Boolean(sample.mask_path)} /></div> : <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center"><ImageOff size={30} className="mb-1 text-gray-300" /><p className="text-sm text-gray-600">当前范围还没有{normal ? "正常参考图" : "缺陷样本"}</p><p className="text-xs leading-5 text-gray-400">切换类别或批次，或返回浏览完成 OK / NG 分拣。</p></div>}
    </div>

    <div className="px-4 pb-4 pt-3">
      <div className="flex min-h-10 items-center justify-between gap-2">
        <div className="min-w-0"><p className="truncate text-sm text-gray-700" title={sample?.relative_path || sample?.filename}>{sample?.filename || (loading ? "正在读取样本…" : "暂无图片")}</p>{sample && <p className="mt-0.5 truncate text-xs text-gray-400">{[!normal && sample.benchmark_defect_type && sample.benchmark_defect_type !== "good" && sample.benchmark_defect_type !== "normal" ? sample.benchmark_defect_type : null, sample.official_split ? `官方 ${sample.official_split}` : null, normal && sample.ok_grade === "borderline" ? "边界正常" : null].filter(Boolean).join(" · ") || (normal ? "已确认正常" : "已确认异常")}</p>}</div>
        <div className="flex shrink-0 items-center gap-1"><button type="button" aria-label={`上一张${title}`} title="上一张（本页）" className={buttonStyle} disabled={loading || index === 0 || !sample} onClick={() => choose(index - 1)}><ChevronLeft size={16} /></button><span className="min-w-9 text-center text-xs tabular-nums text-gray-500">{sample ? `${index + 1}/${items.length}` : "0/0"}</span><button type="button" aria-label={`下一张${title}`} title="下一张（本页）" className={buttonStyle} disabled={loading || index >= items.length - 1 || !sample} onClick={() => choose(index + 1)}><ChevronRight size={16} /></button></div>
      </div>

      <div className="mt-3 grid min-h-14 grid-cols-4 gap-2 sm:grid-cols-8" aria-label={`${title}缩略图`}>
        {items.map((item, itemIndex) => <button key={`${item.id}:${item.file_hash}`} type="button" title={item.filename} aria-label={`${title} ${itemIndex + 1}：${item.filename}`} aria-pressed={itemIndex === index} className={`aspect-square min-w-0 overflow-hidden rounded-md border bg-gray-50 p-0.5 ${itemIndex === index ? "border-gray-800 ring-1 ring-gray-800" : "border-line hover:border-gray-400"}`} onClick={() => choose(itemIndex)}><LocalBrowseThumbnail key={`${item.id}:${item.file_hash}:${thumbnailReadyKey === itemsKey}`} sampleId={item.id} name={item.filename} fileStatus={item.file_status} contentHash={item.file_hash} deferOriginal={thumbnailReadyKey !== itemsKey} /></button>)}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
        <span className="text-xs text-gray-500">{data && data.total > 0 ? `第 ${data.page} / ${pageCount} 页，每页 ${data.page_size} 张` : "每页最多 8 张"}</span>
        <div className="flex gap-2"><button type="button" className={buttonStyle} disabled={loading || !data || data.page <= 1} onClick={() => data && onPageChange(data.page - 1)}><ChevronLeft size={14} />上一页</button><button type="button" className={buttonStyle} disabled={loading || !data || data.page >= pageCount} onClick={() => data && onPageChange(data.page + 1)}>下一页<ChevronRight size={14} /></button></div>
      </div>
    </div>
  </section>;
}
