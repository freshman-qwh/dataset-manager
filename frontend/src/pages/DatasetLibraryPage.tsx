import { ArrowLeft, ArrowUpRight, BookOpen, Download, Image as ImageIcon, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { datasetLibrary, type DatasetLibraryEntry } from "../data/datasetLibrary";

type FocusFilter = "all" | DatasetLibraryEntry["focus"];

const focusLabels: Record<FocusFilter, string> = {
  all: "全部",
  surface: "表面缺陷",
  logical: "逻辑异常",
  multiview: "多视角",
  "3d": "3D"
};

function DatasetLibraryCard({ entry }: { entry: DatasetLibraryEntry }) {
  const [previewFailed, setPreviewFailed] = useState(false);
  const hasPreview = Boolean(entry.previewUrl) && !previewFailed;

  return (
    <article className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-white shadow-sm">
      <a
        href={hasPreview ? entry.previewUrl : entry.previewSourceUrl}
        target="_blank"
        rel="noreferrer"
        aria-label={`${entry.name} · ${hasPreview ? "查看完整概览图" : "前往官方预览"}`}
        className="flex h-48 min-w-0 items-center justify-center border-b border-line bg-gray-50 p-3 hover:bg-gray-100/70"
      >
        {hasPreview ? (
          <img
            src={entry.previewUrl}
            alt={entry.previewAlt}
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={() => setPreviewFailed(true)}
            className="h-full w-full object-contain"
          />
        ) : (
          <span className="flex flex-col items-center gap-2 px-4 text-center text-sm text-gray-500">
            <ImageIcon size={28} className="text-gray-400" aria-hidden="true" />
            <span>{previewFailed ? "概览图暂时无法加载" : "在官方页面查看概览"}</span>
            <span className="inline-flex items-center gap-1 text-xs underline underline-offset-4">打开官方预览 <ArrowUpRight size={13} /></span>
          </span>
        )}
      </a>
      <div className="flex min-w-0 flex-1 flex-col p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="min-w-0 break-words text-lg font-semibold text-ink">{entry.name}</h2>
          <span className="rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-600">{focusLabels[entry.focus]}</span>
        </div>
        <p className="mt-2 text-sm leading-6 text-gray-600">{entry.summary}</p>
        <p className="mt-3 text-xs leading-5 text-gray-500">{entry.categoryCount} 类 · {entry.imageCountLabel} · {entry.year}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {entry.highlights.map(highlight => <span key={highlight} className="max-w-full break-words rounded-md border border-line px-2 py-1 text-xs text-gray-600">{highlight}</span>)}
        </div>
        <div className="mt-4 space-y-1.5 text-xs leading-5 text-gray-500">
          <p>{entry.accessNote}</p>
          <p>许可：{entry.licenseUrl ? <a href={entry.licenseUrl} target="_blank" rel="noreferrer" className="underline underline-offset-2">{entry.licenseLabel}</a> : entry.licenseLabel}</p>
        </div>
        {entry.focus === "3d" && <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs leading-5 text-gray-600">3D 扩展资源；当前应用不解析点云，可先了解数据与任务。</p>}
        <details className="mt-4 border-t border-line pt-3 text-xs leading-5 text-gray-500">
          <summary className="cursor-pointer text-gray-600">使用说明与来源</summary>
          <div className="mt-3 space-y-2">
            {entry.notes.length > 0 && <ul className="list-disc space-y-1.5 pl-4">{entry.notes.map(note => <li key={note}>{note}</li>)}</ul>}
            <p className="break-words">预览来源：<a href={entry.previewSourceUrl} target="_blank" rel="noreferrer" className="underline underline-offset-2">{entry.previewCredit}</a></p>
            <p>资料核对：{entry.verifiedAt}</p>
          </div>
        </details>
        <div className="mt-auto flex flex-wrap gap-2 pt-5">
          <a href={entry.homepageUrl} target="_blank" rel="noreferrer" aria-label={`${entry.name} · 官方主页`} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">官方主页 <ArrowUpRight size={15} /></a>
          <a href={entry.downloadUrl} target="_blank" rel="noreferrer" aria-label={`${entry.name} · ${entry.downloadLabel}`} title={entry.downloadLabel} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg bg-gray-900 px-3 py-2 text-sm text-white hover:bg-gray-800"><Download size={15} /> 下载入口</a>
        </div>
      </div>
    </article>
  );
}

export default function DatasetLibraryPage() {
  const [search, setSearch] = useState("");
  const [focus, setFocus] = useState<FocusFilter>("all");
  const query = search.trim().toLocaleLowerCase();
  const visibleDatasets = useMemo(() => datasetLibrary.filter(entry => {
    if (focus !== "all" && entry.focus !== focus) return false;
    const searchable = [entry.name, entry.summary, ...entry.highlights, ...entry.notes].join(" ").toLocaleLowerCase();
    return !query || searchable.includes(query);
  }), [focus, query]);

  function clearFilters() {
    setSearch("");
    setFocus("all");
  }

  return (
    <main className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-white/90">
        <div className="mx-auto max-w-7xl px-5 py-5">
          <Link to="/" className="inline-flex min-h-10 items-center gap-2 text-sm text-gray-500 hover:text-gray-900"><ArrowLeft size={17} /> 返回我的数据集</Link>
          <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="flex items-center gap-2 text-2xl font-semibold text-ink"><BookOpen size={24} /> 数据集图书馆</h1>
              <p className="mt-2 text-sm leading-6 text-gray-500">精选工业视觉异常检测数据集，先看样例与任务，再前往官方获取数据。</p>
            </div>
            <span className="rounded-md border border-line bg-gray-50 px-2.5 py-1.5 text-xs text-gray-600">工业视觉 · 异常检测</span>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl space-y-6 px-5 py-6">
        <div className="rounded-xl border border-line bg-white px-5 py-4 text-sm leading-6 text-gray-600">
          <p>下载并解压后，返回“我的数据集”创建项目，扫描本地图片目录。</p>
          <p className="mt-1 text-xs text-gray-500">目录介绍可离线浏览；官方预览与下载需要联网。各数据集的获取方式、许可和评估协议以官方说明为准。</p>
        </div>

        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative w-full min-w-0 sm:max-w-md">
              <Search size={18} className="pointer-events-none absolute left-3 top-3 text-gray-400" aria-hidden="true" />
              <input aria-label="搜索异常检测数据集" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索名称、用途或类别" className="min-h-11 w-full min-w-0 rounded-lg border border-line bg-white py-2 pl-10 pr-3 text-sm" />
            </div>
            <p role="status" aria-live="polite" className="text-sm text-gray-500">{visibleDatasets.length} / {datasetLibrary.length} 个数据集</p>
          </div>
          <div className="flex flex-wrap items-center gap-2" aria-label="数据集任务类型">
            {(Object.keys(focusLabels) as FocusFilter[]).map(value => <button key={value} type="button" aria-pressed={focus === value} onClick={() => setFocus(value)} className={`min-h-10 rounded-lg border px-3 py-2 text-sm ${focus === value ? "border-gray-900 bg-gray-900 text-white" : "border-line bg-white text-gray-600 hover:bg-gray-50"}`}>{focusLabels[value]}</button>)}
            {(query || focus !== "all") && <button type="button" onClick={clearFilters} className="inline-flex min-h-10 items-center gap-1 rounded-lg px-2 py-2 text-sm text-gray-500 hover:text-gray-900"><X size={15} /> 清除筛选</button>}
          </div>
        </div>

        {visibleDatasets.length > 0 ? (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{visibleDatasets.map(entry => <DatasetLibraryCard key={entry.id} entry={entry} />)}</div>
        ) : (
          <div className="rounded-xl border border-dashed border-line bg-white px-5 py-12 text-center">
            <Search size={30} className="mx-auto text-gray-300" aria-hidden="true" />
            <h2 className="mt-3 text-base font-semibold text-ink">没有找到匹配的数据集</h2>
            <p className="mt-2 text-sm leading-6 text-gray-500">试试其他名称或任务类型，也可清除条件查看全部资源。</p>
            <button type="button" onClick={clearFilters} className="mt-5 rounded-lg border border-line px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">查看全部数据集</button>
          </div>
        )}
      </section>
    </main>
  );
}
