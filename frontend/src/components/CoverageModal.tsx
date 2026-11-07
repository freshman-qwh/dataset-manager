import { useEffect, useRef, useState } from "react";

import { getCoverage, getCoverageSamples } from "../api/dailyTools";
import type { CoverageCounts, CoverageRead, CoverageSamplesRead, CoverageStatus } from "../types/dailyTools";
import LocalBrowsePreview from "./LocalBrowsePreview";
import LocalBrowseThumbnail from "./LocalBrowseThumbnail";
import Modal from "./Modal";

interface Props { open: boolean; datasetId: number; onClose: () => void }
interface CellQuery { category_id: number | null; batch_id: number | null; status: CoverageStatus; page: number; title: string }
const labels: Record<CoverageStatus, string> = { all: "全部", normal: "OK", anomaly: "NG", pending: "待定", untriaged: "未分拣", stale: "判定过期", unavailable: "文件不可用" };
const statuses: Exclude<CoverageStatus, "all">[] = ["normal", "anomaly", "pending", "untriaged", "stale", "unavailable"];
const empty: CoverageCounts = { total: 0, normal: 0, anomaly: 0, pending: 0, untriaged: 0, stale: 0, unavailable: 0 };
const button = "min-h-9 rounded-lg border border-line px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-35";

export default function CoverageModal({ open, datasetId, onClose }: Props) {
  const [data, setData] = useState<CoverageRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [categoryPage, setCategoryPage] = useState(1);
  const [batchPage, setBatchPage] = useState(1);
  const [cell, setCell] = useState<CellQuery | null>(null);
  const [samples, setSamples] = useState<{ key: string; value: CoverageSamplesRead } | null>(null);
  const [cellLoading, setCellLoading] = useState(false);
  const [cellError, setCellError] = useState("");
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const previewRef = useRef(previewIndex); previewRef.current = previewIndex;
  const cellKey = JSON.stringify([datasetId, cell]);

  useEffect(() => {
    setData(null); setCell(null); setSamples(null); setPreviewIndex(null); setCategoryPage(1); setBatchPage(1);
  }, [datasetId, open]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setError("");
    void getCoverage(datasetId, controller.signal).then((value) => { if (!controller.signal.aborted) setData(value); })
      .catch(() => { if (!controller.signal.aborted) setError("覆盖表加载失败，请重试。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, datasetId, version]);
  useEffect(() => {
    if (!open || !cell) return;
    const controller = new AbortController(); setCellLoading(true); setCellError(""); setPreviewIndex(null);
    void getCoverageSamples(datasetId, cell, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setSamples({ key: cellKey, value }); })
      .catch(() => { if (!controller.signal.aborted) setCellError("样本加载失败，请重试。"); })
      .finally(() => { if (!controller.signal.aborted) setCellLoading(false); });
    return () => controller.abort();
  }, [open, datasetId, cellKey, version]);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow; document.body.style.overflow = "hidden";
    const dialog = container.current?.closest('[role="dialog"]'); dialog?.querySelector<HTMLButtonElement>('button[title="关闭"]')?.focus();
    const key = (event: KeyboardEvent) => {
      if (previewRef.current !== null) return;
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled)') ?? []);
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls[controls.length - 1]?.focus(); }
      if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) { event.preventDefault(); controls[0]?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = overflow; previous?.focus(); };
  }, [open]);

  const current = data?.dataset_id === datasetId ? data : null;
  const currentSamples = samples?.key === cellKey ? samples.value : null;
  const cells = new Map(current?.cells.map((item) => [`${item.category_id}:${item.batch_id}`, item]));
  const categories = current?.categories.slice((categoryPage - 1) * 20, categoryPage * 20) ?? [];
  const batches = current?.batches.slice((batchPage - 1) * 4, batchPage * 4) ?? [];
  function showCell(categoryId: number | null, batchId: number | null, status: CoverageStatus, title: string) {
    setCell({ category_id: categoryId, batch_id: batchId, status, page: 1, title });
  }

  return <><Modal open={open} title="类别 × 批次覆盖表" onClose={onClose} size="xl"><div ref={container} className="space-y-4 p-3 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><p className="max-w-xl text-xs leading-5 text-gray-500">按已登记图片统计。OK/NG 与正常缺陷对照使用相同有效判定，包含官方真值；待定、未分拣、过期及不可用图片分别计数。点击数量查看对应样本。</p><button type="button" disabled={loading || cellLoading} onClick={() => setVersion((value) => value + 1)} className={button}>刷新统计</button></div>
    {loading && <p role="status" className="py-6 text-sm text-gray-500">正在汇总类别和批次…</p>}
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {current && !loading && !error && <><p className="text-xs text-gray-600">共 {current.totals.total} 张图片 · OK {current.totals.normal} · NG {current.totals.anomaly} · 待定 {current.totals.pending} · 未分拣 {current.totals.untriaged} · 过期 {current.totals.stale} · 不可用 {current.totals.unavailable}</p>
      {current.totals.total === 0 && <p className="rounded-lg bg-gray-50 p-4 text-sm text-gray-500">暂无已登记图片。添加图片后可在此检查各类别、批次的数据覆盖。</p>}
      <div className="max-h-[42vh] overflow-auto rounded-lg border border-line"><table className="w-full border-collapse text-left text-xs"><thead className="sticky top-0 z-10 bg-gray-50"><tr><th scope="col" className="min-w-28 border-b border-line p-3 font-medium text-gray-600">对象类别</th>{batches.map((batch) => <th key={String(batch.id)} scope="col" className="min-w-44 border-b border-l border-line p-3 font-medium text-gray-600"><span className="block max-w-52 break-words">{batch.name}</span></th>)}</tr></thead><tbody>{categories.map((category) => <tr key={String(category.id)}><th scope="row" className="max-w-48 border-b border-line p-3 align-top font-medium text-gray-600"><span className="block break-words">{category.name}</span></th>{batches.map((batch) => {
        const count = cells.get(`${category.id}:${batch.id}`) ?? empty;
        const title = `${category.name} · ${batch.name}`;
        return <td key={String(batch.id)} className="border-b border-l border-line p-2 align-top"><button type="button" disabled={!count.total} aria-label={`${title} 全部 ${count.total} 张`} onClick={() => showCell(category.id, batch.id, "all", title)} className="mb-1 min-h-8 rounded px-2 font-medium text-gray-700 hover:bg-gray-100 disabled:text-gray-300">共 {count.total}</button><div className="grid grid-cols-2 gap-1">{statuses.map((status) => <button key={status} type="button" disabled={!count[status]} aria-label={`${title} ${labels[status]} ${count[status]} 张`} onClick={() => showCell(category.id, batch.id, status, title)} className={`min-h-8 rounded px-2 py-1 text-left hover:bg-gray-100 disabled:text-gray-300 ${status === "anomaly" ? "text-red-700" : status === "normal" ? "text-green-700" : "text-gray-500"}`}>{labels[status]} {count[status]}</button>)}</div></td>;
      })}</tr>)}</tbody></table></div>
      <div className="flex flex-wrap justify-between gap-3 text-xs text-gray-500"><div className="flex items-center gap-2"><button type="button" disabled={categoryPage <= 1} onClick={() => setCategoryPage((value) => value - 1)} className={button}>上一组类别</button><span>{categoryPage} / {Math.max(1, Math.ceil(current.categories.length / 20))}</span><button type="button" disabled={categoryPage * 20 >= current.categories.length} onClick={() => setCategoryPage((value) => value + 1)} className={button}>下一组类别</button></div><div className="flex items-center gap-2"><button type="button" disabled={batchPage <= 1} onClick={() => setBatchPage((value) => value - 1)} className={button}>上一组批次</button><span>{batchPage} / {Math.max(1, Math.ceil(current.batches.length / 4))}</span><button type="button" disabled={batchPage * 4 >= current.batches.length} onClick={() => setBatchPage((value) => value + 1)} className={button}>下一组批次</button></div></div>
    </>}
    {cell && <section className="space-y-3 border-t border-line pt-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="min-w-0 break-words text-sm font-medium text-gray-700">{cell.title} · {labels[cell.status]}</h3><button type="button" onClick={() => setCell(null)} className={button}>收起样本</button></div>
      {cellLoading && <p role="status" className="text-sm text-gray-500">正在加载样本…</p>}{cellError && <p role="alert" className="text-sm text-red-700">{cellError}<button type="button" onClick={() => setVersion((value) => value + 1)} className="ml-2 underline">重试</button></p>}
      {currentSamples && !cellLoading && !cellError && <><div className="grid grid-cols-1 gap-2 sm:grid-cols-3">{currentSamples.items.map((sample, index) => <button key={sample.id} type="button" onClick={() => setPreviewIndex(index)} className="flex min-w-0 items-center gap-3 rounded-lg border border-line p-2 text-left hover:bg-gray-50"><span className="h-16 w-16 shrink-0"><LocalBrowseThumbnail key={`${sample.id}:${sample.file_hash}`} sampleId={sample.id} name={sample.filename} contentHash={sample.file_hash} fileStatus={sample.file_status} /></span><span className="min-w-0"><span className="block truncate text-xs font-medium text-gray-700" title={sample.filename}>{sample.filename}</span><span className="mt-1 block break-all text-[11px] text-gray-500">{sample.absolute_path}</span></span></button>)}</div>{!currentSamples.total && <p className="text-sm text-gray-500">当前没有符合条件的图片，数据可能已变化，请刷新统计。</p>}<div className="flex flex-wrap items-center justify-end gap-2 text-xs text-gray-500"><span>{currentSamples.total} 张 · 第 {currentSamples.page} 页</span><button type="button" disabled={currentSamples.page <= 1} onClick={() => setCell({ ...cell, page: currentSamples.page - 1 })} className={button}>上一页样本</button><button type="button" disabled={currentSamples.page * currentSamples.page_size >= currentSamples.total} onClick={() => setCell({ ...cell, page: currentSamples.page + 1 })} className={button}>下一页样本</button></div></>}
    </section>}
  </div></Modal>{open && currentSamples && previewIndex !== null && currentSamples.items[previewIndex] && <LocalBrowsePreview sample={currentSamples.items[previewIndex]} index={previewIndex} count={currentSamples.items.length} onClose={() => setPreviewIndex(null)} onNavigate={(offset) => setPreviewIndex((value) => value === null ? null : Math.max(0, Math.min(currentSamples.items.length - 1, value + offset)))} />}</>;
}
