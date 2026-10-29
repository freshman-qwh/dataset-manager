import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getTriagePolicy, getTriageStats, listDefectTypes } from "../api/client";
import type { Dataset } from "../types/dataset";
import type { DefectType, TriagePolicy, TriageStats } from "../types/triage";

interface Props {
  dataset: Dataset;
  onScan: () => void;
  onQuality: () => void;
  onFilter: () => void;
  onPrepare?: () => void;
  onGroups?: () => void;
}

export default function IndustrialOverview({ dataset, onScan, onQuality, onFilter, onPrepare, onGroups }: Props) {
  const [params, setParams] = useSearchParams();
  const [stats, setStats] = useState<TriageStats | null>(null);
  const [policy, setPolicy] = useState<TriagePolicy | null>(null);
  const [defects, setDefects] = useState<DefectType[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setError("");
    Promise.all([getTriageStats(dataset.id), getTriagePolicy(dataset.id), listDefectTypes(dataset.id)])
      .then(([s, p, d]) => { if (alive) { setStats(s); setPolicy(p); setDefects(d); } })
      .catch(() => { if (alive) setError("分拣状态读取失败，请检查数据库维护状态后重试。"); });
    return () => { alive = false; };
  }, [dataset.id, dataset.revision]);

  function filter(values: Record<string, string>) {
    setParams(current => {
      const next = new URLSearchParams(current);
      for (const key of ["triage_status", "ok_grade", "triage_outdated", "defect_severity", "defect_type_id", "capture_group_id", "capture_batch_id"]) next.delete(key);
      for (const [key, value] of Object.entries(values)) if (value) next.set(key, value);
      return next;
    });
    onFilter();
  }
  function change(key: string, value: string) {
    setParams(current => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value); else next.delete(key);
      if (key === "triage_status" && value !== "ok") next.delete("ok_grade");
      if (key === "ok_grade" && value) next.set("triage_status", "ok");
      return next;
    });
    onFilter();
  }
  const cards = [
    ["未分拣", stats?.by_status.untriaged ?? 0, { triage_status: "untriaged" }],
    ["完全 OK", stats?.by_ok_grade.clear ?? 0, { triage_status: "ok", ok_grade: "clear" }],
    ["临界可接受", stats?.by_ok_grade.borderline ?? 0, { triage_status: "ok", ok_grade: "borderline" }],
    ["NG 异常", stats?.by_status.ng ?? 0, { triage_status: "ng" }],
    ["待定", stats?.by_status.pending ?? 0, { triage_status: "pending" }],
    ["判定待复核", stats?.outdated ?? 0, { triage_outdated: "true" }]
  ] as const;
  return <section className="space-y-4 rounded-xl border border-line bg-white p-5 shadow-sm" aria-label="工业异常检测工作区">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs text-gray-500">工业异常检测 · 本地数据准备</p><h2 className="mt-2 text-xl font-semibold">{!stats?.total_images ? "导入第一批工业图片" : (stats.by_status.untriaged ?? 0) > 0 ? "继续分拣，建立可信的正常与异常样本" : "复核分组与判定，准备独立评估数据"}</h2>
        <p className="mt-2 text-sm text-gray-500">扫描 → 分拣 → 工件分组 → 独立划分 → 数据包。图像级准备无需先画框。</p></div>
      <div className="flex flex-wrap gap-2">
        {!stats?.total_images ? <button className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white" onClick={onScan}>扫描图片</button> : <Link className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white" to={`/datasets/${dataset.id}/triage?queue=untriaged`}>继续分拣</Link>}
        {onGroups && <button className="rounded-lg border border-line px-4 py-2 text-sm" onClick={onGroups}>采集分组</button>}
        <button className="rounded-lg border border-line px-4 py-2 text-sm" onClick={onPrepare ?? onQuality}>{onPrepare ? "准备异常检测数据" : "检查数据质量"}</button>
      </div>
    </div>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">{cards.map(([label, count, values]) => <button key={label} disabled={"ok_grade" in values && !policy?.split_ok} onClick={() => filter({ ...values })} className="rounded-lg border border-line bg-gray-50 p-3 text-left hover:bg-gray-100 disabled:opacity-60"><span className="text-xs text-gray-500">{label}</span><strong className="mt-1 block text-xl">{stats ? count : "…"}</strong></button>)}</div>
    {stats && (stats.by_status.ok ?? 0) > (stats.by_ok_grade.clear ?? 0) + (stats.by_ok_grade.borderline ?? 0) && <button className="text-sm text-amber-800 underline" onClick={() => filter({ triage_status: "ok" })}>有统一 OK 图片尚未确认正常等级，查看并复核</button>}
    <p className="text-xs text-gray-500">完全 OK 是训练候选，仍需检查原图、整组成员和重复。临界默认排除，NG 仅用于验证/测试。旧统一 OK 不自动升级为完全正常。</p>
    <div className="flex flex-wrap gap-2" aria-label="工业分拣筛选">
      <select aria-label="分拣判定筛选" value={params.get("triage_status") ?? ""} onChange={e => change("triage_status", e.target.value)} className="rounded-lg border border-line px-3 py-2 text-sm"><option value="">全部判定</option><option value="untriaged">未分拣</option><option value="ok">OK</option><option value="ng">NG</option><option value="pending">待定</option></select>
      {policy?.split_ok && <select aria-label="正常等级筛选" value={params.get("ok_grade") ?? ""} onChange={e => change("ok_grade", e.target.value)} className="rounded-lg border border-line px-3 py-2 text-sm"><option value="">全部正常等级</option><option value="clear">完全 OK</option><option value="borderline">临界可接受</option></select>}
      <select aria-label="判定有效性筛选" value={params.get("triage_outdated") ?? ""} onChange={e => change("triage_outdated", e.target.value)} className="rounded-lg border border-line px-3 py-2 text-sm"><option value="">全部有效性</option><option value="true">待复核</option><option value="false">当前有效 / 未分拣</option></select>
      {policy?.ng_grouping.includes("defect_type") && <select aria-label="缺陷类型筛选" value={params.get("defect_type_id") ?? ""} onChange={e => change("defect_type_id", e.target.value)} className="rounded-lg border border-line px-3 py-2 text-sm"><option value="">全部缺陷类型</option>{defects.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>}
      {policy?.ng_grouping.includes("severity") && <select aria-label="缺陷程度筛选" value={params.get("defect_severity") ?? ""} onChange={e => change("defect_severity", e.target.value)} className="rounded-lg border border-line px-3 py-2 text-sm"><option value="">全部程度</option><option value="mild">轻微</option><option value="moderate">中等</option><option value="severe">严重</option></select>}
      <button onClick={() => filter({})} className="rounded-lg border border-line px-3 py-2 text-sm">清除分拣筛选</button>
      <button onClick={onQuality} className="rounded-lg border border-line px-3 py-2 text-sm">数据质量</button>
    </div>
  </section>;
}
