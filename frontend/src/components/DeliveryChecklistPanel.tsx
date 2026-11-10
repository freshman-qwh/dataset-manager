import { ArrowUpRight, ImageOff, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getSampleFileUrl } from "../api/client";
import type { ChecklistCoverageRow, ChecklistSample, DeliveryChecklist, DeliveryIssue, DeliveryTarget } from "../types/deliveryChecklist";
import Modal from "./Modal";

interface Props { checklist: DeliveryChecklist; datasetId: number }
const targets: Record<DeliveryTarget, string> = { training_package: "独立训练数据包", evaluation: "本机独立评估", exploration: "正常一致性探索" };
const severityTitles: Record<DeliveryIssue["severity"], string> = { blocker: "必须处理", excluded: "本次明确排除", notice: "补充建议与说明" };
const actionCopy: Record<DeliveryIssue["action"], string> = { triage: "核对人工判定", groups: "核对工件与批次", scope: "检查本次数据范围", collect: "补充独立采集数据", review: "复核图片与登记信息" };

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function actualCounts(value: unknown): Array<{ split: "train" | "val" | "test"; normal: number; abnormal: number }> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const record = value as Record<string, unknown>;
  const result: Array<{ split: "train" | "val" | "test"; normal: number; abnormal: number }> = [];
  for (const split of ["train", "val", "test"] as const) {
    const row = record[split];
    if (!row || typeof row !== "object" || Array.isArray(row)) continue;
    const values = row as Record<string, unknown>;
    const normal = count(values.normal), abnormal = count(values.abnormal);
    if (normal !== null && abnormal !== null) result.push({ split, normal, abnormal });
  }
  return result;
}

function CoverageTable({ label, rows }: { label: string; rows: ChecklistCoverageRow[] }) {
  return <section className="min-w-0 space-y-2"><h4 className="text-sm font-medium">{label}</h4>{rows.length === 0 ? <p className="text-xs text-gray-500">当前范围没有对应记录。</p> : <div className="overflow-x-auto"><table className="w-full min-w-[580px] text-left text-xs"><thead><tr>{["名称", "图片", "有效正常", "有效异常", "待确认 / 不可用", "正常独立组", "异常独立组"].map(text => <th key={text} className="p-2 font-medium text-gray-500">{text}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.id ?? "unassigned"} className="border-t border-line"><td className="max-w-48 break-all p-2">{row.name}</td><td className="p-2 tabular-nums">{row.total}</td><td className="p-2 tabular-nums">{row.normal}</td><td className="p-2 tabular-nums">{row.abnormal}</td><td className="p-2 tabular-nums">{row.pending}</td><td className="p-2 tabular-nums">{row.normal_groups}</td><td className="p-2 tabular-nums">{row.abnormal_groups}</td></tr>)}</tbody></table></div>}</section>;
}

function SamplePreview({ sample, onClose }: { sample: ChecklistSample; onClose: () => void }) {
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [retry, setRetry] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    root.current?.querySelector<HTMLButtonElement>("button")?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const controls = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = previousOverflow; previousFocus?.focus(); };
  }, []);
  return <div ref={root} className="fixed inset-0 z-[60]"><Modal open title="查看问题样例" onClose={onClose} size="lg"><div className="space-y-3 p-4"><p className="break-all text-sm">{sample.relative_path}</p><div className="relative flex min-h-48 items-center justify-center rounded-lg bg-gray-50 p-2">{failed ? <div role="alert" className="space-y-3 p-6 text-center text-sm text-gray-600"><ImageOff size={28} className="mx-auto" /><p>原图暂时无法读取，请确认文件可访问后重试。</p><button type="button" className="min-h-10 rounded-lg border border-line px-3" onClick={() => { setRetry(value => value + 1); setFailed(false); setReady(false); }}>重新读取原图</button></div> : <><img key={retry} src={`${getSampleFileUrl(sample.id)}?checklist_retry=${retry}`} alt={`问题样例 ${sample.relative_path}`} onLoad={() => setReady(true)} onError={() => setFailed(true)} className="max-h-[65vh] max-w-full object-contain" />{!ready && <p role="status" className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-gray-500"><Loader2 size={18} className="animate-spin" />正在读取原图…</p>}</>}</div><p className="text-xs leading-5 text-gray-500">样例用于人工核对，不修改判定。这里只展示所选的一张图片，不代表问题范围已全部复核。</p><button type="button" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm" onClick={onClose}><X size={15} />关闭样例</button></div></Modal></div>;
}

export default function DeliveryChecklistPanel(props: Props) {
  return <ChecklistContent key={props.checklist.plan.plan_id} {...props} />;
}

function ChecklistContent({ checklist, datasetId }: Props) {
  const [preview, setPreview] = useState<ChecklistSample | null>(null);
  const counts = actualCounts(checklist.plan.summary.counts).filter(row => checklist.target !== "exploration" || row.split !== "test");
  const included = count(checklist.plan.summary.included_count), excluded = count(checklist.plan.summary.excluded_count);
  return <section aria-label="交付目标验收清单" className="min-w-0 space-y-4 rounded-xl border border-line bg-white p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h3 className="font-semibold">交付目标验收清单 · {targets[checklist.target]}</h3><p className="mt-1 text-xs leading-5 text-gray-500">对应当前范围与数据版本 {checklist.dataset_revision}。数据、规则或原图变化后需重新检查。</p></div><span className={`rounded-lg px-3 py-2 text-sm font-medium ${checklist.ready ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>{checklist.ready ? "数据检查通过，可继续确认" : "存在必须处理项"}</span></div>
    {counts.length > 0 && <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" aria-label="本目标实际划分数量">{counts.map(row => <div key={row.split} className="rounded-lg bg-gray-50 p-3 text-sm"><strong>{row.split === "train" ? checklist.target === "training_package" ? "训练" : "拟合" : row.split === "val" ? checklist.target === "exploration" ? "正常验证" : "验证" : "测试"}</strong><p className="mt-1 text-xs text-gray-600">正常 {row.normal} / 异常 {row.abnormal}</p></div>)}</div>}
    {(included !== null || excluded !== null) && <p className="text-sm text-gray-600">{included !== null ? `实际纳入 ${included} 张` : ""}{included !== null && excluded !== null ? "，" : ""}{excluded !== null ? `排除 ${excluded} 张` : ""}。{checklist.target === "exploration" ? "仅检查正常图片的一致性，不产生异常检出率或正式测试结论。" : "数量来自本次已检查方案，整组隔离优先。"}</p>}
    {(["blocker", "excluded", "notice"] as const).map(severity => {
      const issues = checklist.issues.filter(issue => issue.severity === severity);
      if (issues.length === 0) return null;
      return <div key={severity} className="space-y-2"><h4 className="text-sm font-semibold">{severityTitles[severity]} · {issues.length} 项</h4>{issues.map(issue => <article key={issue.key} className={`min-w-0 space-y-2 rounded-lg border p-3 ${severity === "blocker" ? "border-amber-200 bg-amber-50" : "border-line bg-gray-50"}`}>
        <div className="flex flex-wrap justify-between gap-2"><p className="min-w-0 break-words text-sm font-medium">{issue.title}</p><span className="text-xs text-gray-500">{issue.count > 0 ? `涉及 ${issue.count} 张` : "方案级检查"}</span></div>
        <p className="break-words text-sm leading-6 text-gray-600">{issue.guidance}</p><p className="text-xs text-gray-500">下一步：{actionCopy[issue.action]}</p>
        {issue.samples.length > 0 && <details className="rounded-lg border border-line bg-white"><summary className="cursor-pointer px-3 py-2 text-xs text-gray-600">查看问题样例 · 展示 {issue.samples.length} 张{issue.sample_ids.length > issue.samples.length ? ` / 涉及 ${issue.sample_ids.length} 张` : ""}</summary><div className="space-y-2 border-t border-line p-2">{issue.samples.map(sample => <div key={sample.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded p-1 text-xs"><button type="button" className="min-w-0 flex-1 break-all text-left underline underline-offset-2" onClick={() => setPreview(sample)}>{sample.relative_path}</button><a target="_blank" rel="noreferrer noopener" href={`/datasets/${datasetId}/triage?queue=current_filter&sample=${sample.id}`} className="inline-flex min-h-9 shrink-0 items-center gap-1 rounded border border-line bg-white px-2">分拣这张<ArrowUpRight size={13} /></a></div>)}<p className="px-1 text-xs leading-5 text-gray-500">链接只定位这一张样例；不会自动创建整组复核队列或扩大本次交付范围。涉及分组的问题可从分拣页查看工件多视角。</p></div></details>}
      </article>)}</div>;
    })}
    {!checklist.issues.length && <p className="rounded-lg bg-gray-50 p-3 text-sm text-gray-600">当前范围未发现本目标的阻断或排除项，可继续使用本次已检查的方案。</p>}
    <details className="min-w-0 rounded-lg border border-line"><summary className="cursor-pointer px-3 py-2 text-sm text-gray-700">查看当前范围的类别、批次与缺陷覆盖</summary><div className="min-w-0 space-y-4 border-t border-line p-3"><p className="text-xs leading-5 text-gray-500">数量限定在本次所选范围，包含被排除的图片。有效正常/异常与独立组分别统计；待定、过期和不可用图片不充当有效真值。组数不等于图片数量，也不是足够采集的统一门槛。</p><CoverageTable label="对象类别" rows={checklist.coverage.categories} /><CoverageTable label="采集批次" rows={checklist.coverage.batches} /><section className="min-w-0 space-y-2"><h4 className="text-sm font-medium">缺陷类型</h4>{checklist.coverage.defects.length === 0 ? <p className="text-xs text-gray-500">当前范围没有已登记的缺陷类型。</p> : <div className="overflow-x-auto"><table className="w-full min-w-80 text-left text-xs"><thead><tr><th className="p-2 font-medium text-gray-500">缺陷类型</th><th className="p-2 font-medium text-gray-500">图片</th><th className="p-2 font-medium text-gray-500">独立组</th></tr></thead><tbody>{checklist.coverage.defects.map(row => <tr key={row.id} className="border-t border-line"><td className="break-all p-2">{row.name}</td><td className="p-2 tabular-nums">{row.total}</td><td className="p-2 tabular-nums">{row.groups}</td></tr>)}</tbody></table></div>}</section></div></details>
    {checklist.notes.length > 0 && <div className="space-y-1 border-t border-line pt-3 text-xs leading-5 text-gray-500">{checklist.notes.map((note, index) => <p key={index}>{note}</p>)}</div>}
    {preview && <SamplePreview key={preview.id} sample={preview} onClose={() => setPreview(null)} />}
  </section>;
}
