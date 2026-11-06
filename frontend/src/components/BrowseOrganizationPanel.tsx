import { useEffect, useState } from "react";
import { getOrganization } from "../api/organization";
import type { DatasetOrganization } from "../types/organization";
import LocalBrowseThumbnail from "./LocalBrowseThumbnail";

interface Props {
  datasetId: number;
  revision: number;
  categoryId?: number;
  batchId?: number;
  onFilter: (category?: number, batch?: number) => void;
  onManage: () => void;
}

export default function BrowseOrganizationPanel({ datasetId, revision, categoryId, batchId, onFilter, onManage }: Props) {
  const [organization, setOrganization] = useState<DatasetOrganization | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setOrganization(null); setFailed(false);
    void getOrganization(datasetId).then((value) => { if (active) setOrganization(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [datasetId, revision]);
  return <section aria-label="类别与批次筛选" className="mb-4 rounded-xl border border-line bg-white p-3 sm:p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 flex-wrap gap-3">
        <label className="text-xs text-gray-500">对象类别<select aria-label="对象类别筛选" value={categoryId ?? ""} onChange={(event) => onFilter(event.target.value ? Number(event.target.value) : undefined, batchId)} className="ml-2 max-w-52 rounded-lg border border-line bg-white px-2 py-2 text-sm text-gray-700"><option value="">全部类别</option>{organization?.categories.map((category) => <option key={category.id} value={category.id}>{category.name} · {category.sample_count}</option>)}</select></label>
        <label className="text-xs text-gray-500">采集批次<select aria-label="采集批次筛选" value={batchId ?? ""} onChange={(event) => onFilter(categoryId, event.target.value ? Number(event.target.value) : undefined)} className="ml-2 max-w-52 rounded-lg border border-line bg-white px-2 py-2 text-sm text-gray-700"><option value="">全部批次</option>{organization?.batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.name} · {batch.sample_count}</option>)}</select></label>
      </div>
      <button type="button" onClick={onManage} className="rounded-lg px-2 py-2 text-xs text-gray-600 underline underline-offset-4 hover:bg-gray-50">管理类别与批次</button>
    </div>
    {failed && <p role="alert" className="mt-2 text-xs text-red-700">类别与批次暂时无法加载，可刷新目录重试。</p>}
    {organization && organization.categories.length > 0 && !categoryId && <details className="mt-3" open={organization.categories.length <= 20}>
      <summary className="cursor-pointer py-1 text-xs text-gray-500">按类别查看 · {organization.categories.length} 类</summary>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">{organization.categories.map((category) => <button key={category.id} type="button" onClick={() => onFilter(category.id, batchId)} className="flex min-w-0 items-center gap-2 rounded-lg border border-line p-2 text-left hover:border-gray-400">
        <span className="block h-12 w-12 shrink-0 overflow-hidden rounded-md bg-gray-100"><LocalBrowseThumbnail sampleId={category.cover_sample_id ?? null} contentHash={category.cover_file_hash ?? ""} name={`${category.name} 类别预览`} /></span>
        <span className="min-w-0"><span className="block truncate text-xs font-medium text-gray-700" title={category.name}>{category.name}</span><span className="mt-1 block text-[11px] text-gray-400">{category.sample_count} 张 · 正常 {category.normal_count} / 异常 {category.anomaly_count}</span></span>
      </button>)}</div>
    </details>}
    <p className="mt-2 text-[11px] text-gray-400">类别描述图片中的对象；批次记录采集来源，文件夹保留磁盘结构。</p>
  </section>;
}
