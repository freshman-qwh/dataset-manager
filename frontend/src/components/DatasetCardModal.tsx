import { Download, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getDatasetCard } from "../api/datasetCard";
import type { DatasetCard } from "../types/datasetCard";
import { renderDatasetCard } from "../utils/renderDatasetCard";
import Modal from "./Modal";

interface Props { datasetId: number; open: boolean; onClose: () => void }
interface Preview { datasetId: number; url: string; data: DatasetCard; failedPreviews: number; loadedPreviews: number }

export default function DatasetCardModal({ datasetId, open, onClose }: Props) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let url: string | undefined;
    setPreview(null); setError(""); setLoading(true);
    void getDatasetCard(datasetId, controller.signal).then(async (data) => {
      const result = await renderDatasetCard(data, controller.signal);
      if (controller.signal.aborted) return;
      url = URL.createObjectURL(result.blob);
      setPreview({ datasetId, url, data, failedPreviews: result.failedPreviews, loadedPreviews: result.loadedPreviews });
    }).catch(() => { if (!controller.signal.aborted) setError("名片生成失败，请检查服务或重新生成。"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [datasetId, open, version]);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow; document.body.style.overflow = "hidden";
    const dialog = container.current?.closest('[role="dialog"]');
    const closeButton = dialog?.querySelector<HTMLButtonElement>('button[title="关闭"]'); closeButton?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]') ?? []);
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = previousOverflow; previousFocus?.focus(); };
  }, [open]);

  const current = open && preview?.datasetId === datasetId ? preview : null;
  function regenerate() { setLoading(true); setPreview(null); setError(""); setVersion((value) => value + 1); }
  function download() {
    if (!current || loading) return;
    const name = current.data.dataset.name.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/[. ]+$/, "").slice(0, 100) || "dataset";
    const anchor = document.createElement("a"); anchor.href = current.url; anchor.download = `${name}_数据集名片.png`; anchor.click();
  }

  return <Modal open={open} title="数据集名片" onClose={onClose} size="xl"><div ref={container} className="space-y-4 p-3 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><p className="max-w-xl text-xs leading-5 text-gray-500">自动汇总已登记数据和代表图片，可直接下载用于汇报。名片不包含原始文件路径。</p><div className="flex flex-wrap gap-2"><button type="button" disabled={loading} onClick={regenerate} className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40"><RefreshCw size={15} />重新生成</button><button type="button" disabled={!current || loading} onClick={download} className="inline-flex min-h-10 items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-2 text-sm text-white disabled:opacity-40"><Download size={15} />下载 PNG</button></div></div>
    {loading && <div role="status" className="flex min-h-64 items-center justify-center rounded-lg border border-line bg-gray-50 px-5 text-sm text-gray-500">正在汇总数据并准备名片…</div>}
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}<button type="button" onClick={regenerate} className="ml-2 underline underline-offset-2">重试</button></div>}
    {current && <><img src={current.url} alt={`${current.data.dataset.name}的数据集名片`} className="block h-auto w-full rounded-lg border border-line bg-white" /><div className="sr-only"><p>{current.data.dataset.name}，{current.data.summary.image_count} 张图片，{current.data.summary.category_count} 个对象类别，{current.data.summary.batch_count} 个采集批次。</p><p>正常 {current.data.summary.normal_count}，异常 {current.data.summary.anomaly_count}，待复核 {current.data.summary.pending_count}，未分拣 {current.data.summary.untriaged_count}，关联 Mask {current.data.summary.mask_count}。</p></div><p role="status" className={`text-xs leading-5 ${current.failedPreviews ? "text-amber-800" : "text-gray-500"}`}>代表图 {current.loadedPreviews} / {Math.min(current.data.preview_samples.length, 8)} 张已读取。{current.failedPreviews > 0 && `${current.failedPreviews} 张无法读取，名片保留了占位；可检查原文件位置后重新生成。`}</p></>}
  </div></Modal>;
}
