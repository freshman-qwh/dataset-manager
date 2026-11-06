import { ArrowRight, Clock3, FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getTriageStats } from "../api/client";
import type { Dataset } from "../types/dataset";
import type { TriageStats } from "../types/triage";
import { getContinueBrowseUrl, getRememberedBrowseLocation, type WorkbenchPreferences } from "../utils/workbenchPreferences";

interface ProjectWorkbenchProps {
  datasets: Dataset[];
  preferences: WorkbenchPreferences;
}

function visitDate(openedAt: number): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(openedAt));
}

export default function ProjectWorkbench({ datasets, preferences }: ProjectWorkbenchProps) {
  const byId = new Map(datasets.map((dataset) => [dataset.id, dataset]));
  const recent = preferences.recent.filter((visit) => byId.has(visit.datasetId)).slice(0, 3);
  const featured = recent.length ? byId.get(recent[0].datasetId) : datasets.find((dataset) => preferences.pinnedDatasetIds.includes(dataset.id)) ?? datasets[0];
  const featuredId = featured?.id;
  const industrialId = featured?.workflow_profile === "industrial_anomaly" && recent.length ? featured.id : null;
  const [triage, setTriage] = useState<TriageStats | null>(null);

  useEffect(() => {
    let active = true;
    setTriage(null);
    if (industrialId) void getTriageStats(industrialId).then((stats) => { if (active) setTriage(stats); }).catch(() => { /* Optional counts must not interrupt browsing. */ });
    return () => { active = false; };
  }, [industrialId]);

  if (!featured || !featuredId) return null;
  const location = getRememberedBrowseLocation(featuredId, preferences);
  const folder = location.get("folder");
  const savedParts = [folder, location.has("category") ? "保留类别筛选" : null, location.has("batch") ? "保留批次筛选" : null, location.has("page") ? `第 ${location.get("page")} 页` : null].filter(Boolean);
  const currentTriage = triage?.dataset_id === featuredId ? triage : null;
  const pending = currentTriage?.by_status.pending ?? 0;
  const untriaged = currentTriage?.by_status.untriaged ?? 0;

  return (
    <section aria-label="项目工作台" className="mb-6 rounded-xl border border-line bg-white p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold text-ink">项目工作台</h2>
        <p className="text-xs text-gray-400">{recent.length ? "接着上次的位置继续看图" : "打开一个数据集，自动记住浏览位置"}</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0 flex-1 basis-36">
              <h3 className="truncate text-base font-semibold text-ink" title={featured.name}>{featured.name}</h3>
              <p className="mt-1 truncate text-xs text-gray-500" title={savedParts.join(" · ") || undefined}>{savedParts.join(" · ") || `${featured.project || "未归属项目"} · ${featured.sample_count.toLocaleString()} 个样本`}</p>
            </div>
            <Link to={getContinueBrowseUrl(featuredId, preferences)} className="inline-flex min-h-10 shrink-0 items-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800">
              <FolderOpen size={16} />{recent.length ? "继续浏览" : "浏览数据集"}<ArrowRight size={15} />
            </Link>
          </div>
          {currentTriage && (untriaged > 0 || pending > 0 || currentTriage.outdated > 0) && (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-gray-500" aria-label={`${featured.name}的分拣进度`}>
              {untriaged > 0 && <Link className="underline decoration-gray-300 underline-offset-4 hover:text-gray-900" to={`/datasets/${featuredId}/triage?queue=untriaged`}>未分拣 {untriaged.toLocaleString()}</Link>}
              {pending > 0 && <Link className="underline decoration-gray-300 underline-offset-4 hover:text-gray-900" to={`/datasets/${featuredId}?triage_status=pending`}>待定 {pending.toLocaleString()}</Link>}
              {currentTriage.outdated > 0 && <Link className="underline decoration-gray-300 underline-offset-4 hover:text-gray-900" to={`/datasets/${featuredId}?triage_outdated=true`}>判定需复核 {currentTriage.outdated.toLocaleString()}</Link>}
            </div>
          )}
        </div>
        {recent.length > 0 && <div className="min-w-0 border-t border-line pt-3 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
          <p className="mb-1 flex items-center gap-1.5 text-xs text-gray-400"><Clock3 size={13} />最近打开</p>
          <ul className="space-y-0.5">
            {recent.map((visit) => <li key={visit.datasetId}><Link to={getContinueBrowseUrl(visit.datasetId, preferences)} className="flex min-h-8 min-w-0 items-center justify-between gap-3 rounded-md px-1 py-1 text-xs text-gray-600 hover:bg-gray-50"><span className="truncate" title={byId.get(visit.datasetId)!.name}>{byId.get(visit.datasetId)!.name}</span><time className="shrink-0 text-gray-400" dateTime={new Date(visit.openedAt).toISOString()}>{visitDate(visit.openedAt)}</time></Link></li>)}
          </ul>
        </div>}
      </div>
    </section>
  );
}
