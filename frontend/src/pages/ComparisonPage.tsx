import { ArrowLeft, RefreshCw, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import axios from "axios";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { UIEvent } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";

import { getDataset } from "../api/client";
import { getComparison } from "../api/comparison";
import { getOrganization, organizationError } from "../api/organization";
import ComparisonColumn from "../components/ComparisonColumn";
import type { ComparisonRead, ComparisonSideName } from "../types/comparison";
import type { Dataset } from "../types/dataset";
import type { DatasetOrganization } from "../types/organization";

const buttonStyle = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-35";

function positiveNumber(value: string | null | undefined): number | undefined {
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : undefined;
}

function comparisonError(cause: unknown, fallback: string): string {
  if (axios.isAxiosError(cause) && cause.response?.status === 404) return "该数据集不存在或已被删除，请返回浏览选择其他数据集。";
  return organizationError(cause, fallback);
}

function browseDestination(state: unknown, datasetId: number, categoryId?: number | null, batchId?: number | null): string {
  if (state && typeof state === "object" && "returnTo" in state && typeof state.returnTo === "string") {
    const returnTo = state.returnTo;
    if (returnTo.startsWith("/browse?") && !returnTo.includes("\\")) {
      const target = new URL(returnTo, "http://dataset-manager.local");
      if (target.origin === "http://dataset-manager.local" && target.pathname === "/browse" && target.searchParams.get("dataset") === String(datasetId)) return `${target.pathname}${target.search}`;
    }
  }
  const query = new URLSearchParams({ dataset: String(datasetId), recursive: "1" });
  if (categoryId) query.set("category", String(categoryId));
  if (batchId) query.set("batch", String(batchId));
  return `/browse?${query}`;
}

export default function ComparisonPage() {
  const { datasetId: routeId } = useParams();
  const datasetId = positiveNumber(routeId);
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const categoryId = positiveNumber(params.get("category"));
  const batchId = positiveNumber(params.get("batch"));
  const normalPage = positiveNumber(params.get("normalPage")) ?? 1;
  const anomalyPage = positiveNumber(params.get("anomalyPage")) ?? 1;
  const [version, setVersion] = useState(0);
  const [metadata, setMetadata] = useState<{ key: string; dataset: Dataset; organization: DatasetOrganization } | null>(null);
  const [response, setResponse] = useState<{ key: string; normalKey: string; anomalyKey: string; data: ComparisonRead } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [metadataFailure, setMetadataFailure] = useState<{ key: string; message: string } | null>(null);
  const metadataKey = JSON.stringify([datasetId, version]);
  const filterKey = JSON.stringify([datasetId, categoryId, batchId]);
  const normalKey = JSON.stringify([filterKey, normalPage, version]);
  const anomalyKey = JSON.stringify([filterKey, anomalyPage, version]);
  const requestKey = JSON.stringify([datasetId, categoryId, batchId, normalPage, anomalyPage, version]);
  const info = metadata?.key === metadataKey ? metadata : null;
  const data = response?.key === requestKey ? response.data : null;
  const normalData = response?.normalKey === normalKey ? response.data.normal : null;
  const anomalyData = response?.anomalyKey === anomalyKey ? response.data.anomaly : null;
  const error = metadataFailure?.key === metadataKey ? metadataFailure.message : failure?.key === requestKey ? failure.message : null;
  const loading = Boolean(datasetId) && !data && !error;
  const [zoom, setZoom] = useState(1);
  const normalViewport = useRef<HTMLDivElement>(null);
  const anomalyViewport = useRef<HTMLDivElement>(null);
  const pan = useRef({ x: 0, y: 0 });
  const pendingScroll = useRef<Partial<Record<ComparisonSideName, { left: number; top: number }>>>({});

  useEffect(() => {
    if (!datasetId) return;
    const controller = new AbortController();
    let active = true;
    void Promise.all([getDataset(datasetId, controller.signal), getOrganization(datasetId, controller.signal)]).then(([dataset, organization]) => {
      if (active) setMetadata({ key: metadataKey, dataset, organization });
    }).catch((cause: unknown) => {
      if (active && !controller.signal.aborted) setMetadataFailure({ key: metadataKey, message: comparisonError(cause, "数据集信息读取失败，请重试。") });
    });
    return () => { active = false; controller.abort(); };
  }, [datasetId, metadataKey]);

  useEffect(() => {
    if (!datasetId) return;
    const controller = new AbortController();
    let active = true;
    void getComparison(datasetId, { category_id: categoryId, batch_id: batchId, normal_page: normalPage, anomaly_page: anomalyPage, page_size: 8 }, controller.signal).then((value) => {
      if (active) setResponse({ key: requestKey, normalKey, anomalyKey, data: value });
    }).catch((cause: unknown) => {
      if (active && !controller.signal.aborted) setFailure({ key: requestKey, message: comparisonError(cause, "对照图片读取失败，请重试。") });
    });
    return () => { active = false; controller.abort(); };
  }, [datasetId, categoryId, batchId, normalPage, anomalyPage, requestKey, normalKey, anomalyKey]);

  function resetPan() {
    pan.current = { x: 0, y: 0 };
    pendingScroll.current = {};
    normalViewport.current?.scrollTo(0, 0);
    anomalyViewport.current?.scrollTo(0, 0);
  }

  function syncPan(side: ComparisonSideName, event: UIEvent<HTMLDivElement>) {
    const origin = event.currentTarget;
    const expected = pendingScroll.current[side];
    if (expected && Math.abs(origin.scrollLeft - expected.left) < 1 && Math.abs(origin.scrollTop - expected.top) < 1) {
      delete pendingScroll.current[side];
      return;
    }
    delete pendingScroll.current[side];
    pan.current = { x: origin.scrollWidth > origin.clientWidth ? origin.scrollLeft / (origin.scrollWidth - origin.clientWidth) : 0, y: origin.scrollHeight > origin.clientHeight ? origin.scrollTop / (origin.scrollHeight - origin.clientHeight) : 0 };
    const otherSide = side === "normal" ? "anomaly" : "normal";
    const target = side === "normal" ? anomalyViewport.current : normalViewport.current;
    if (!target) return;
    const left = pan.current.x * Math.max(0, target.scrollWidth - target.clientWidth);
    const top = pan.current.y * Math.max(0, target.scrollHeight - target.clientHeight);
    if (Math.abs(target.scrollLeft - left) < 1 && Math.abs(target.scrollTop - top) < 1) return;
    pendingScroll.current[otherSide] = { left, top };
    target.scrollTo(left, top);
  }

  useLayoutEffect(() => { resetPan(); }, [filterKey]);

  useLayoutEffect(() => {
    for (const [side, viewport] of [["normal", normalViewport.current], ["anomaly", anomalyViewport.current]] as const) {
      if (!viewport) continue;
      const left = pan.current.x * Math.max(0, viewport.scrollWidth - viewport.clientWidth);
      const top = pan.current.y * Math.max(0, viewport.scrollHeight - viewport.clientHeight);
      pendingScroll.current[side] = { left, top };
      viewport.scrollTo(left, top);
    }
  }, [zoom, data]);

  function changeFilter(key: "category" | "batch", value: string) {
    resetPan();
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value); else next.delete(key);
      if (key === "batch" && !categoryId && data?.category_id) next.set("category", String(data.category_id));
      next.delete("normalPage");
      next.delete("anomalyPage");
      return next;
    });
  }

  function changePage(side: ComparisonSideName, page: number) {
    resetPan();
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (!categoryId && data?.category_id) next.set("category", String(data.category_id));
      next.set(side === "normal" ? "normalPage" : "anomalyPage", String(page));
      return next;
    });
  }

  const returnTo = browseDestination(location.state, datasetId ?? 0, categoryId ?? data?.category_id, batchId);
  if (!datasetId) return <div className="mx-auto max-w-3xl p-6"><p role="alert" className="mb-4 text-sm text-red-700">数据集地址无效。</p><Link to="/browse" className={buttonStyle}><ArrowLeft size={16} />返回浏览</Link></div>;

  return <div className="mx-auto max-w-[1600px] space-y-5 px-3 py-5 sm:px-6 lg:px-8">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1"><Link to={returnTo} className="mb-3 inline-flex min-h-9 items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900"><ArrowLeft size={16} />返回浏览位置</Link><h1 className="text-xl font-semibold tracking-tight text-gray-900">正常与缺陷对照</h1><p className="mt-1 break-words text-sm text-gray-500">{info?.dataset.name ?? (error ? "数据集信息暂不可用" : "正在读取数据集…")}<span className="mx-2 text-gray-300">/</span>在同一对象类别下，对比正常参考与已确认的缺陷。</p></div>
      <button type="button" onClick={() => setVersion((value) => value + 1)} disabled={loading} className={buttonStyle}><RefreshCw size={15} className={loading ? "animate-spin" : ""} />刷新</button>
    </header>

    <div className="flex flex-wrap items-end justify-between gap-4 rounded-xl border border-line bg-white p-4">
      <div className="flex min-w-0 basis-full flex-col gap-3 sm:basis-auto sm:flex-1 sm:flex-row sm:flex-wrap">
        <label className="min-w-0 flex-1 sm:min-w-44 sm:flex-none"><span className="mb-1.5 block text-xs text-gray-500">对象类别</span><select aria-label="对象类别" className="h-10 w-full max-w-full rounded-lg border border-line bg-white px-3 text-sm sm:max-w-64" disabled={!info || loading} value={String(categoryId ?? data?.category_id ?? "")} onChange={(event) => changeFilter("category", event.target.value)}><option value="">{info && info.organization.categories.length === 0 ? "未设置类别" : "自动选择一个类别"}</option>{info?.organization.categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
        <label className="min-w-0 flex-1 sm:min-w-44 sm:flex-none"><span className="mb-1.5 block text-xs text-gray-500">采集批次</span><select aria-label="采集批次" className="h-10 w-full max-w-full rounded-lg border border-line bg-white px-3 text-sm sm:max-w-64" disabled={!info || loading} value={batchId ?? ""} onChange={(event) => changeFilter("batch", event.target.value)}><option value="">全部批次</option>{info?.organization.batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.name}</option>)}</select></label>
      </div>
      <div><span className="mb-1.5 block text-xs text-gray-500">两侧同步缩放</span><div className="flex flex-wrap items-center gap-1.5"><button type="button" aria-label="缩小两侧图片" className={buttonStyle} disabled={zoom <= 1} onClick={() => setZoom((value) => Math.max(1, value - 0.5))}><ZoomOut size={16} /></button><span className="min-w-11 text-center text-sm tabular-nums text-gray-600">{Math.round(zoom * 100)}%</span><button type="button" aria-label="放大两侧图片" className={buttonStyle} disabled={zoom >= 4} onClick={() => setZoom((value) => Math.min(4, value + 0.5))}><ZoomIn size={16} /></button><button type="button" className={buttonStyle} onClick={() => { setZoom(1); resetPan(); }}><RotateCcw size={14} />还原</button></div></div>
    </div>

    {error ? <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5"><p className="break-words text-sm text-red-800">{error}</p><button type="button" className={`${buttonStyle} mt-3`} onClick={() => setVersion((value) => value + 1)}><RefreshCw size={14} />重试</button></div> : <>
      <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2"><ComparisonColumn side="normal" data={normalData} loading={!normalData && loading} zoom={zoom} viewportRef={normalViewport} onScroll={(event) => syncPan("normal", event)} onPageChange={(page) => changePage("normal", page)} onSampleChange={resetPan} /><ComparisonColumn side="anomaly" data={anomalyData} loading={!anomalyData && loading} zoom={zoom} viewportRef={anomalyViewport} onScroll={(event) => syncPan("anomaly", event)} onPageChange={(page) => changePage("anomaly", page)} onSampleChange={resetPan} /></div>
      <p className="px-1 text-xs leading-5 text-gray-400">放大后可拖动或滚动大图，两侧位置同步；聚焦某侧大图后，左右方向键切换该侧本页图片。{data && data.excluded_count > 0 ? ` 当前范围有 ${data.excluded_count.toLocaleString()} 张待定、未确认或不可用的图片未进入对照。` : ""}</p>
    </>}
  </div>;
}
