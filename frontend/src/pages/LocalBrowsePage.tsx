import { ArrowLeft, ArrowUp, ChevronLeft, ChevronRight, Folder, FolderOpen, Images, RefreshCw, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { createThumbnailJob, getJob, getSampleFileUrl, listDatasets } from "../api/client";
import { browseLocalDataset } from "../api/localBrowse";
import LocalBrowsePreview from "../components/LocalBrowsePreview";
import BrowseFileCard from "../components/BrowseFileCard";
import BrowseOrganizationPanel from "../components/BrowseOrganizationPanel";
import BrowseDailyTools from "../components/BrowseDailyTools";
import OrganizationModal from "../components/OrganizationModal";
import DatasetCardModal from "../components/DatasetCardModal";
import LocalBrowseThumbnail from "../components/LocalBrowseThumbnail";
import type { Dataset } from "../types/dataset";
import type { LocalBrowseQuery, LocalBrowseResponse } from "../types/localBrowse";
import { getRememberedBrowseLocation as rememberedLocation, rememberDatasetVisit } from "../utils/workbenchPreferences";

const buttonStyle = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-35";

interface BrowsePreviewState {
  scopeKey: string;
  data: LocalBrowseResponse;
  query: LocalBrowseQuery;
  index: number;
}

function positivePage(value: string | null): number {
  const page = Number(value);
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

function sourceRelativePath(absolutePath: string, root: string): string {
  const path = absolutePath.replace(/\\/g, "/");
  const prefix = root.replace(/\\/g, "/").replace(/\/$/, "") + "/";
  return path.toLocaleLowerCase().startsWith(prefix.toLocaleLowerCase()) ? path.slice(prefix.length) : path;
}

function browseCaption(absolutePath: string, data: LocalBrowseResponse): string {
  if (data.source_root) return sourceRelativePath(absolutePath, data.source_root);
  const normalized = absolutePath.replace(/\\/g, "/");
  const source = [...data.sources].sort((left, right) => right.path.length - left.path.length).find((entry) => normalized.toLocaleLowerCase().startsWith(entry.path.replace(/\\/g, "/").replace(/\/$/, "").toLocaleLowerCase() + "/"));
  if (!source) return absolutePath;
  const relative = sourceRelativePath(absolutePath, source.path);
  return data.sources.length === 1 ? relative : `${source.path.replace(/\\/g, "/").split("/").filter(Boolean).pop()}/${relative}`;
}

export default function LocalBrowsePage() {
  const [params, setParams] = useSearchParams();
  const paramsKey = params.toString();
  const datasetId = Number(params.get("dataset"));
  const folder = params.get("folder") ?? "";
  const source = params.get("source") ?? "";
  const recursive = params.get("recursive") === "1";
  const search = params.get("q") ?? "";
  const fileType = params.get("type") === "all" ? "" : "image";
  const page = positivePage(params.get("page"));
  const folderPage = positivePage(params.get("folderPage"));
  const categoryId = params.has("category") ? positivePage(params.get("category")) : undefined;
  const batchId = params.has("batch") ? positivePage(params.get("batch")) : undefined;
  const allSources = Boolean(categoryId || batchId) && !source;
  const locationKey = JSON.stringify([datasetId, source, folder, categoryId, batchId]);
  const size = params.get("size") === "small" ? 150 : params.get("size") === "large" ? 300 : 210;
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [listVersion, setListVersion] = useState(0);
  const [datasetSearch, setDatasetSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [organizationOpen, setOrganizationOpen] = useState(false);
  const [cardOpen, setCardOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [searchDraft, setSearchDraft] = useState({ locationKey, value: search });
  const draftSearch = searchDraft.locationKey === locationKey ? searchDraft.value : search;
  const [composing, setComposing] = useState(false);
  const [version, setVersion] = useState(0);
  const [response, setResponse] = useState<{ key: string; data: LocalBrowseResponse } | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [thumbnailRevision, setThumbnailRevision] = useState(0);
  const [thumbnailReadyKey, setThumbnailReadyKey] = useState("");
  const [preview, setPreview] = useState<BrowsePreviewState | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const previewRef = useRef<BrowsePreviewState | null>(null);
  const previewRequest = useRef<AbortController | null>(null);
  const pendingFocus = useRef<number | null>(null);
  const latestParams = useRef(params);
  latestParams.current = params;
  const selected = datasets.find((dataset) => dataset.id === datasetId);
  const requestKey = JSON.stringify([datasetId, source, folder, recursive, search, fileType, page, folderPage, version, categoryId, batchId]);
  const currentRequestKey = useRef(requestKey);
  currentRequestKey.current = requestKey;
  const data = response?.key === requestKey ? response.data : null;
  const error = errorKey === requestKey;
  const loading = Boolean(selected) && !data && !error;
  const datasetNeedle = datasetSearch.trim().toLocaleLowerCase();
  const visibleDatasets = datasets.filter((dataset) => `${dataset.name} ${dataset.root_path ?? ""} ${dataset.project ?? ""}`.toLocaleLowerCase().includes(datasetNeedle) && (!projectFilter || (projectFilter === "none" ? !dataset.project_id : String(dataset.project_id) === projectFilter)));
  const projects = [...new Map(datasets.filter((dataset) => dataset.project_id).map((dataset) => [dataset.project_id!, { id: dataset.project_id!, name: dataset.project ?? "项目" }])).values()];

  function setDraftSearch(value: string) { setSearchDraft({ locationKey, value }); }

  function changeQuery(changes: Record<string, string | null>, replace = false) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key); else next.set(key, value);
      }
      return next;
    }, { replace });
  }

  function chooseDataset(id: number) {
    const next = rememberedLocation(id);
    next.set("dataset", String(id));
    setParams(next);
  }

  function openFolder(path: string) {
    changeQuery({ folder: path, page: null, folderPage: null, q: null });
  }

  function openPreview(index: number) {
    if (!data?.items[index]) return;
    previewRequest.current?.abort();
    previewRequest.current = null;
    const next: BrowsePreviewState = {
      scopeKey: requestKey,
      data,
      index,
      query: {
        folder, recursive, search, file_type: fileType, page: data.page, page_size: data.page_size,
        folder_page: folderPage, folder_page_size: 24, category_id: categoryId, batch_id: batchId,
        all_sources: allSources, ...(source ? { source_root: source } : {})
      }
    };
    previewRef.current = next;
    setPreview(next);
    setPreviewLoading(false);
    setPreviewError("");
  }

  function closePreview() {
    const current = previewRef.current;
    previewRequest.current?.abort();
    previewRequest.current = null;
    previewRef.current = null;
    setPreview(null);
    setPreviewLoading(false);
    setPreviewError("");
    if (!current || current.scopeKey !== currentRequestKey.current) return;
    pendingFocus.current = current.data.items[current.index]?.id ?? null;
    if (current.data.page !== page) changeQuery({ page: current.data.page > 1 ? String(current.data.page) : null }, true);
  }

  async function navigatePreview(offset: number) {
    const current = previewRef.current;
    // A synchronous lock also covers repeated keydown events before React renders.
    if (!current || previewRequest.current || current.scopeKey !== currentRequestKey.current) return;
    const globalIndex = (current.data.page - 1) * current.data.page_size + current.index;
    const target = globalIndex + offset;
    if (target < 0 || target >= current.data.total) return;
    const nextIndex = current.index + offset;
    setPreviewError("");
    if (nextIndex >= 0 && nextIndex < current.data.items.length) {
      const next = { ...current, index: nextIndex };
      previewRef.current = next;
      setPreview(next);
      return;
    }
    const controller = new AbortController();
    previewRequest.current = controller;
    setPreviewLoading(true);
    try {
      const nextPage = Math.floor(target / current.data.page_size) + 1;
      const result = await browseLocalDataset(current.data.dataset_id, { ...current.query, page: nextPage }, controller.signal);
      if (controller.signal.aborted || previewRef.current !== current || current.scopeKey !== currentRequestKey.current) return;
      // Refuse a clamped page after records disappear, rather than jumping to a different position.
      if (result.page !== nextPage || result.total !== current.data.total || !result.items.length || target >= result.total) {
        setPreviewError("浏览范围中的图片已变化，请关闭预览并刷新后继续。");
        return;
      }
      const index = offset > 0 ? 0 : result.items.length - 1;
      const next = { ...current, data: result, index };
      previewRef.current = next;
      setPreview(next);
    } catch {
      if (!controller.signal.aborted) setPreviewError("相邻图片加载失败，当前图片已保留。请再次切换重试。");
    } finally {
      if (previewRequest.current === controller) {
        previewRequest.current = null;
        setPreviewLoading(false);
      }
    }
  }

  useEffect(() => {
    let active = true;
    setListLoading(true); setListError(false);
    void listDatasets().then((items) => { if (active) setDatasets(items); }).catch(() => { if (active) setListError(true); }).finally(() => { if (active) setListLoading(false); });
    return () => { active = false; };
  }, [listVersion]);

  useEffect(() => {
    if (params.has("dataset") || listLoading || !datasets.length) return;
    const next = params.toString() ? new URLSearchParams(params) : rememberedLocation(datasets[0].id);
    next.set("dataset", String(datasets[0].id));
    setParams(next, { replace: true });
  }, [datasets, listLoading, params, setParams]);

  useEffect(() => {
    if (!selected || !data || data.dataset_id !== datasetId) return;
    const verified = new URLSearchParams(paramsKey);
    if (data.folder) verified.set("folder", data.folder); else verified.delete("folder");
    if (data.page > 1) verified.set("page", String(data.page)); else verified.delete("page");
    if (data.folder_page > 1) verified.set("folderPage", String(data.folder_page)); else verified.delete("folderPage");
    rememberDatasetVisit(datasetId, verified);
  }, [data, datasetId, paramsKey, selected]);

  useEffect(() => { setSearchDraft({ locationKey, value: search }); }, [locationKey, search]);
  useEffect(() => {
    if (composing || searchDraft.locationKey !== locationKey || draftSearch === search) return;
    const timer = window.setTimeout(() => {
      const next = new URLSearchParams(latestParams.current);
      if (draftSearch) next.set("q", draftSearch); else next.delete("q");
      next.delete("page"); setParams(next, { replace: true });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [composing, draftSearch, locationKey, search, searchDraft.locationKey, setParams]);

  useEffect(() => {
    previewRequest.current?.abort();
    previewRequest.current = null;
    previewRef.current = null;
    setPreview(null);
    setPreviewLoading(false);
    setPreviewError("");
    if (!selected) return;
    const controller = new AbortController();
    void browseLocalDataset(datasetId, {
      folder, recursive, search, file_type: fileType, page, page_size: 60,
      folder_page: folderPage, folder_page_size: 24, category_id: categoryId, batch_id: batchId, all_sources: allSources, ...(source ? { source_root: source } : {})
    }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setResponse({ key: requestKey, data: result });
    }).catch(() => { if (!controller.signal.aborted) setErrorKey(requestKey); });
    return () => controller.abort();
  }, [allSources, datasetId, fileType, folder, folderPage, page, recursive, requestKey, search, selected, source]);

  useEffect(() => () => { previewRequest.current?.abort(); }, []);

  useEffect(() => {
    if (preview || !data || pendingFocus.current === null) return;
    const sampleId = pendingFocus.current;
    const target = document.querySelector<HTMLElement>(`[data-browse-sample-id="${sampleId}"]`);
    if (!target) return;
    const frame = window.requestAnimationFrame(() => {
      target.scrollIntoView({ block: "center", behavior: "auto" });
      target.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
      pendingFocus.current = null;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [data, preview]);

  useEffect(() => {
    if (!preview) return;
    const adjacent = [preview.data.items[preview.index - 1], preview.data.items[preview.index + 1]];
    const images = adjacent.filter((sample) => sample?.file_type === "image" && sample.file_status === "normal").map((sample) => {
      const image = new Image();
      image.src = getSampleFileUrl(sample.id);
      return image;
    });
    return () => { images.forEach((image) => { image.removeAttribute("src"); }); };
  }, [preview]);

  useEffect(() => {
    if (!data || !selected) return;
    const imageIds = data.items.filter((sample) => sample.file_type === "image" && sample.file_status === "normal").map((sample) => sample.id);
    const coverIds = data.folders.flatMap((entry) => entry.cover_sample_id === null ? [] : [entry.cover_sample_id]);
    const ids = Array.from(new Set([...imageIds, ...coverIds]));
    if (!ids.length) { setThumbnailReadyKey(requestKey); return; }
    let active = true;
    let timer: number | undefined;
    async function poll(jobId: number) {
      try {
        const job = await getJob(jobId);
        if (!active) return;
        if (job.status === "queued" || job.status === "running") timer = window.setTimeout(() => void poll(jobId), 750);
        else { setThumbnailReadyKey(requestKey); setThumbnailRevision((value) => value + 1); }
      } catch { if (active) setThumbnailReadyKey(requestKey); }
    }
    void createThumbnailJob(datasetId, ids).then((result) => {
      if (!active) return;
      if (result.job) { window.dispatchEvent(new Event("dataset-manager:jobs-changed")); void poll(result.job.id); }
      else { setThumbnailReadyKey(requestKey); setThumbnailRevision((value) => value + 1); }
    }).catch(() => { if (active) setThumbnailReadyKey(requestKey); });
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [data, datasetId, requestKey, selected]);

  useEffect(() => { setSelectedIds([]); }, [locationKey, page, folderPage, search, fileType]);

  const breadcrumbs = folder.split("/").filter(Boolean);
  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const folderPageCount = data ? Math.max(1, Math.ceil(data.folders_total / data.folder_page_size)) : 1;

  return (
    <main className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-white"><div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6"><div className="flex items-center gap-3"><Link to="/" aria-label="返回我的数据集" className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"><ArrowLeft size={19} /></Link><div><h1 className="text-lg font-semibold text-ink">本地浏览</h1><p className="mt-0.5 text-xs text-gray-500">分散的数据集，一处切换查看</p></div></div><Link to="/" className={buttonStyle}>管理数据集</Link></div></header>
      <div className="mx-auto grid max-w-[1600px] gap-5 p-4 sm:p-6 lg:grid-cols-[250px_minmax(0,1fr)]">
        <aside aria-label="数据集位置" className="min-w-0 lg:sticky lg:top-5 lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto">
          <label className="mb-3 block text-xs text-gray-500">项目<select aria-label="按项目浏览" value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)} className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-700"><option value="">全部项目</option><option value="none">未归属项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
          <div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold text-ink">我的数据集 <span className="ml-1 font-normal text-gray-400">{datasets.length}</span></h2><button type="button" aria-label="刷新数据集列表" onClick={() => setListVersion((value) => value + 1)} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"><RefreshCw size={15} /></button></div>
          {listLoading ? <p className="p-3 text-sm text-gray-500">正在加载数据集…</p> : listError ? <div role="alert" className="rounded-lg border border-red-200 bg-white p-3 text-sm text-red-700">无法加载数据集。<button type="button" onClick={() => setListVersion((value) => value + 1)} className="ml-2 underline">重试</button></div> : datasets.length === 0 ? <p className="rounded-lg border border-line bg-white p-4 text-sm leading-6 text-gray-500">还没有登记数据集。<Link to="/" className="text-gray-900 underline underline-offset-2">添加本地目录</Link>后即可浏览。</p> : <>
            <label className="mb-3 block lg:hidden"><span className="sr-only">切换数据集</span><select value={selected?.id ?? ""} onChange={(event) => chooseDataset(Number(event.target.value))} className="w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm"><option value="" disabled>选择数据集</option>{visibleDatasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.sample_count} 个文件</option>)}</select></label>
            <div className="hidden lg:block"><div className="relative mb-3"><Search size={15} className="pointer-events-none absolute left-3 top-3 text-gray-400" /><input aria-label="查找数据集或位置" value={datasetSearch} onChange={(event) => setDatasetSearch(event.target.value)} placeholder="查找名称或位置" className="w-full rounded-lg border border-line bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-gray-500" /></div><div className="space-y-1">{visibleDatasets.map((dataset) => <button key={dataset.id} type="button" aria-current={dataset.id === datasetId ? "true" : undefined} onClick={() => chooseDataset(dataset.id)} className={`w-full min-w-0 rounded-lg border p-3 text-left transition ${dataset.id === datasetId ? "border-gray-900 bg-gray-900 text-white" : "border-transparent text-gray-600 hover:border-line hover:bg-white"}`}><span className="flex items-start gap-2"><FolderOpen size={17} className="mt-0.5 shrink-0" /><span className="min-w-0 flex-1"><span className="block break-words text-sm font-medium">{dataset.name}</span><span className={`mt-1 block truncate text-xs ${dataset.id === datasetId ? "text-gray-300" : "text-gray-400"}`} title={dataset.root_path ?? undefined}>{dataset.root_path ?? "未设置来源目录"}</span><span className={`mt-1 block text-xs ${dataset.id === datasetId ? "text-gray-300" : "text-gray-400"}`}>{dataset.sample_count.toLocaleString()} 个文件</span></span></span></button>)}{visibleDatasets.length === 0 && <p className="px-3 py-5 text-sm text-gray-500">没有匹配的数据集。</p>}</div></div>
          </>}
        </aside>
        <section aria-label="目录浏览" className="min-w-0">
          {!listLoading && !listError && !selected && datasets.length > 0 ? <div className="rounded-xl border border-line bg-white p-8 text-sm text-gray-500">该数据集不存在，请选择其他数据集。</div> : selected && <>
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 className="break-words text-xl font-semibold text-ink">{selected.name}</h2><p className="mt-1 text-xs leading-5 text-gray-500">按原目录浏览，也可展开子文件夹连续看图。</p></div><div className="flex flex-wrap gap-2"><Link to={`/datasets/${datasetId}/compare${categoryId || batchId ? `?${new URLSearchParams({ ...(categoryId ? { category: String(categoryId) } : {}), ...(batchId ? { batch: String(batchId) } : {}) })}` : ""}`} state={{ returnTo: `/browse?${paramsKey}` }} className={buttonStyle}>正常与缺陷对照</Link><button type="button" onClick={() => setCardOpen(true)} className={buttonStyle}>数据集名片</button><Link to={`/datasets/${datasetId}`} className={buttonStyle}>进入数据准备</Link></div></div>
            <BrowseOrganizationPanel datasetId={datasetId} revision={version} categoryId={categoryId} batchId={batchId} onManage={() => setOrganizationOpen(true)} onFilter={(category, batch) => changeQuery({ category: category ? String(category) : null, batch: batch ? String(batch) : null, folder: null, page: null, folderPage: null, q: null, source: null, recursive: category || batch ? "1" : params.get("recursive") })} />
            {categoryId && selected.workflow_profile === "industrial_anomaly" && <Link to={`/datasets/${datasetId}/validate`} state={{ currentQuery: { category_id: categoryId, ...(batchId ? { batch_id: batchId } : {}) } }} className="mb-3 inline-flex rounded-lg border border-line bg-white px-3 py-2 text-xs text-gray-600 hover:bg-gray-50">验证此类别</Link>}
            {selectedIds.length > 0 && <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-600"><span>已选择 {selectedIds.length} 张</span><button type="button" onClick={() => setOrganizationOpen(true)} className="underline underline-offset-4">设置类别或批次</button><button type="button" onClick={() => setSelectedIds([])} className="text-xs">取消选择</button></div>}
            <BrowseDailyTools key={datasetId} datasetId={datasetId} sampleIds={selectedIds} />
            <div className="mb-4 rounded-xl border border-line bg-white p-3 sm:p-4">
              {data && (data.sources.length > 1 || allSources) ? <label className="mb-3 flex min-w-0 flex-col gap-1.5 text-xs text-gray-500"><span>来源目录</span><select aria-label="来源目录" value={data.source_root} onChange={(event) => changeQuery({ source: event.target.value, folder: null, q: null, page: null, folderPage: null })} className="max-w-full rounded-lg border border-line bg-white px-2 py-2 text-sm text-gray-600">{allSources && <option value="">全部来源</option>}{data.sources.map((entry) => <option key={entry.path} value={entry.path}>{entry.path} · {entry.sample_count} 个文件</option>)}</select></label> : <p className="mb-3 truncate text-xs text-gray-400" title={data?.source_root || selected.root_path || undefined}>{data?.source_root || selected.root_path || "尚无已登记的来源"}</p>}
              <nav aria-label="文件夹路径" className="mb-3 flex flex-wrap items-center gap-1 text-sm"><button type="button" onClick={() => openFolder("")} className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 hover:bg-gray-100 ${folder ? "text-gray-500" : "font-medium text-ink"}`}><FolderOpen size={16} />根目录</button>{breadcrumbs.map((segment, index) => <span key={`${index}:${segment}`} className="inline-flex min-w-0 items-center gap-1"><ChevronRight size={13} className="shrink-0 text-gray-300" /><button type="button" title={segment} onClick={() => openFolder(breadcrumbs.slice(0, index + 1).join("/"))} className={`max-w-full break-all rounded-md px-2 py-1.5 text-left hover:bg-gray-100 ${index === breadcrumbs.length - 1 ? "font-medium text-ink" : "text-gray-500"}`}>{segment}</button></span>)}</nav>
              <div className="flex flex-wrap items-center gap-3"><div className="relative min-w-0 basis-52 flex-1"><Search size={16} className="pointer-events-none absolute left-3 top-3 text-gray-400" /><input aria-label="搜索当前目录文件" value={draftSearch} onChange={(event) => setDraftSearch(event.target.value)} onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)} placeholder="搜索文件名或路径" className="w-full rounded-lg border border-line py-2.5 pl-9 pr-3 text-sm outline-none focus:border-gray-500" /></div><label className="inline-flex min-h-10 items-center gap-2 text-sm text-gray-600"><input type="checkbox" checked={recursive || allSources} disabled={allSources} onChange={(event) => changeQuery({ recursive: event.target.checked ? "1" : null, page: null })} className="h-4 w-4 accent-gray-900" />包含子文件夹</label><button type="button" aria-label="刷新当前目录" onClick={() => setVersion((value) => value + 1)} className={buttonStyle}><RefreshCw size={16} /></button></div>
            </div>
            {error ? <div role="alert" className="rounded-xl border border-red-200 bg-white p-5 text-sm text-red-700"><p>目录加载失败。该位置可能已失效，或服务暂时不可用。</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => setVersion((value) => value + 1)} className={buttonStyle}>重新加载</button><button type="button" onClick={() => changeQuery({ source: null, folder: null, page: null, folderPage: null, q: null })} className={buttonStyle}>回到根目录</button></div></div> : loading ? <div role="status" className="flex min-h-64 items-center justify-center rounded-xl border border-line bg-white text-sm text-gray-400">正在读取目录…</div> : data && <>
              {(data.folders_total > 0 || folder) && <div className="mb-5"><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h3 className="text-xs font-medium text-gray-500">文件夹 <span className="ml-1 text-gray-400">{data.folders_total}</span></h3>{folder && <button type="button" onClick={() => openFolder(breadcrumbs.slice(0, -1).join("/"))} className="inline-flex min-h-9 items-center gap-1 text-xs text-gray-500 hover:text-gray-900"><ArrowUp size={14} />上一级</button>}</div><div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{data.folders.map((entry) => <button key={entry.path} type="button" onClick={() => openFolder(entry.path)} className="flex min-w-0 items-center gap-3 rounded-lg border border-line bg-white p-3 text-left transition hover:border-gray-400 hover:shadow-sm"><span className="relative h-14 w-16 shrink-0 overflow-hidden rounded-md bg-gray-50">{entry.cover_sample_id !== null ? <LocalBrowseThumbnail key={`${entry.cover_sample_id}:${thumbnailRevision}`} deferOriginal={thumbnailReadyKey !== requestKey} sampleId={entry.cover_sample_id} name={`${entry.name}文件夹预览`} contentHash={entry.cover_file_hash ?? ""} /> : <span className="flex h-full items-center justify-center text-gray-300"><Folder size={25} /></span>}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-gray-700" title={entry.name}>{entry.name}</span><span className="mt-1 block text-xs text-gray-400">{entry.image_count.toLocaleString()} 张图片 · {entry.sample_count.toLocaleString()} 个文件</span></span><ChevronRight size={15} className="shrink-0 text-gray-300" /></button>)}</div>{folderPageCount > 1 && <div className="mt-3 flex flex-wrap items-center justify-end gap-2 text-xs text-gray-500"><button type="button" aria-label="上一页文件夹" disabled={data.folder_page <= 1} onClick={() => changeQuery({ folderPage: String(data.folder_page - 1) })} className={buttonStyle}><ChevronLeft size={15} /></button><span>文件夹 {data.folder_page} / {folderPageCount} 页</span><button type="button" aria-label="下一页文件夹" disabled={data.folder_page >= folderPageCount} onClick={() => changeQuery({ folderPage: String(data.folder_page + 1) })} className={buttonStyle}><ChevronRight size={15} /></button></div>}</div>}
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-medium text-gray-700">{recursive ? "当前目录及子文件夹" : "当前目录"}<span className="ml-2 text-xs font-normal text-gray-400">{data.total.toLocaleString()} {fileType ? "张图片" : "个文件"}</span></h3><div className="flex flex-wrap gap-2"><select aria-label="浏览文件类型" value={fileType || "all"} onChange={(event) => changeQuery({ type: event.target.value === "all" ? "all" : null, page: null })} className="min-h-9 rounded-lg border border-line bg-white px-2 text-xs text-gray-600"><option value="image">仅图片</option><option value="all">全部类型</option></select><select aria-label="缩略图大小" value={size === 150 ? "small" : size === 300 ? "large" : "medium"} onChange={(event) => changeQuery({ size: event.target.value === "medium" ? null : event.target.value }, true)} className="min-h-9 rounded-lg border border-line bg-white px-2 text-xs text-gray-600"><option value="small">小图</option><option value="medium">中图</option><option value="large">大图</option></select></div></div>
              {data.items.length === 0 ? <div className="flex min-h-60 flex-col items-center justify-center rounded-xl border border-dashed border-line bg-white px-5 text-center"><Images size={30} className="text-gray-300" /><p className="mt-3 text-sm text-gray-500">{search ? "没有匹配的文件" : recursive ? "该范围暂无已登记的图片或文件" : "当前目录没有直接存放的图片或文件"}</p>{!recursive && data.folders_total > 0 && <button type="button" onClick={() => changeQuery({ recursive: "1", page: null })} className="mt-3 text-sm text-gray-800 underline underline-offset-4">查看所有子文件夹中的图片</button>}{search && <button type="button" onClick={() => changeQuery({ q: null, page: null })} className="mt-3 text-sm text-gray-800 underline underline-offset-4">清除搜索</button>}{data.total > 0 && page > 1 && <button type="button" onClick={() => changeQuery({ page: null })} className="mt-3 text-sm text-gray-800 underline underline-offset-4">回到第一页</button>}</div> : <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(min(100%, ${size}px), 1fr))` }}>{data.items.map((sample, index) => <div key={sample.id} data-browse-sample-id={sample.id} className="min-w-0"><BrowseFileCard sample={sample} selected={selectedIds.includes(sample.id)} caption={recursive || allSources ? browseCaption(sample.absolute_path, data) : ""} thumbnailRevision={thumbnailRevision} deferOriginal={thumbnailReadyKey !== requestKey} onSelect={() => setSelectedIds((current) => current.includes(sample.id) ? current.filter((id) => id !== sample.id) : [...current, sample.id])} onPreview={() => openPreview(index)} /></div>)}</div>}
              {pageCount > 1 && <div className="mt-5 flex flex-wrap items-center justify-center gap-3 text-xs text-gray-500"><button type="button" disabled={data.page <= 1} onClick={() => changeQuery({ page: String(data.page - 1) })} className={buttonStyle}><ChevronLeft size={15} />上一页</button><span>第 {data.page} / {pageCount} 页</span><button type="button" disabled={data.page >= pageCount} onClick={() => changeQuery({ page: String(data.page + 1) })} className={buttonStyle}>下一页<ChevronRight size={15} /></button></div>}
              <p className="mt-5 text-xs leading-5 text-gray-400">仅浏览已登记文件。目录有新增或移动时，可进入数据准备重新扫描。切换数据集会记住此浏览器中的浏览位置。</p>
            </>}
          </>}
        </section>
      </div>
      {preview && preview.scopeKey === requestKey && preview.data.items[preview.index] && <LocalBrowsePreview sample={preview.data.items[preview.index]} index={(preview.data.page - 1) * preview.data.page_size + preview.index} count={preview.data.total} navigationLoading={previewLoading} navigationError={previewError} onClose={closePreview} onNavigate={(offset) => void navigatePreview(offset)} />}
      {selected && <OrganizationModal datasetId={datasetId} open={organizationOpen} selectedIds={selectedIds} onClose={() => setOrganizationOpen(false)} onUpdated={async () => { setVersion((value) => value + 1); setListVersion((value) => value + 1); }} />}
      {selected && <DatasetCardModal datasetId={datasetId} open={cardOpen} onClose={() => setCardOpen(false)} />}
    </main>
  );
}
