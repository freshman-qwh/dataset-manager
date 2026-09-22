import { Check, ChevronDown, CircleAlert, Info, Loader2 } from "lucide-react";

import type {
  NgGrouping,
  TriagePolicyImpactPreview,
  TriagePolicyValues,
  TriageStats
} from "../types/triage";
import Modal from "./Modal";

const OK_GRANULARITY_OPTIONS = [
  {
    splitOk: false,
    title: "统一 OK（推荐）",
    description: "只记录合格判定，导出到单一 ok/ 目录。"
  },
  {
    splitOk: true,
    title: "细分完全 / 临界 OK",
    description: "适用于需要单独复核边界样本的研究流程。"
  }
];

const NG_GROUPING_OPTIONS: Array<{
  value: NgGrouping;
  title: string;
  description: string;
}> = [
  { value: "none", title: "不细分（推荐）", description: "只判断 NG，导出到单一 ng 目录" },
  { value: "defect_type", title: "按缺陷类别", description: "例如 ng/scratch" },
  { value: "severity", title: "按严重程度", description: "按轻微、中等、严重分目录" },
  { value: "defect_type_and_severity", title: "类别＋程度", description: "例如 ng/scratch/mild" }
];

interface PolicyOptionProps {
  checked: boolean;
  name: string;
  title: string;
  description: string;
  onChange: () => void;
}

function PolicyOption({ checked, name, title, description, onChange }: PolicyOptionProps) {
  return (
    <label
      title={description}
      className={`flex min-h-12 cursor-pointer items-center gap-2 rounded-xl border px-3 py-2.5 transition-colors ${
        checked ? "border-gray-900 bg-gray-50" : "border-line hover:bg-gray-50"
      }`}
    >
      <input type="radio" name={name} checked={checked} onChange={onChange} />
      <span className="min-w-0 flex-1 text-sm font-semibold">{title}</span>
      <Info size={15} aria-hidden="true" className="shrink-0 text-gray-400" />
      <span className="sr-only">说明：{description}</span>
    </label>
  );
}

interface TriagePolicyModalProps {
  open: boolean;
  firstRun: boolean;
  draft: TriagePolicyValues | null;
  stats: TriageStats | null;
  impact: TriagePolicyImpactPreview | null;
  saving: boolean;
  onChange: (value: TriagePolicyValues) => void;
  onCancel: () => void;
  onSubmit: () => void;
}

export default function TriagePolicyModal({
  open,
  firstRun,
  draft,
  stats,
  impact,
  saving,
  onChange,
  onCancel,
  onSubmit
}: TriagePolicyModalProps) {
  if (!draft) return null;

  const needsConfirmation = Boolean(impact?.changed && impact.requires_review_count > 0);

  return (
    <Modal
      open={open}
      title={firstRun ? "开始快速分拣" : "修改分拣规则"}
      onClose={onCancel}
      size="xl"
      dismissible={!firstRun}
    >
      <div className="p-5">
        <details className="group rounded-xl border border-blue-200 bg-blue-50 px-4 py-3">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold text-blue-950">
            <Info size={16} className="shrink-0" />
            <span className="flex-1">
              {firstRun ? "推荐从统一 OK + NG 不细分开始" : "规则修改不会删除已有判定"}
            </span>
            <ChevronDown size={16} className="transition-transform group-open:rotate-180" />
          </summary>
          <p className="mt-2 pl-6 text-xs leading-5 text-blue-800">
            {firstRun
              ? "先选择需要记录的判定粒度；只有确实需要研究级分析时再开启细分。"
              : "新规则用于后续判定与导出解释；已有细分信息继续保留，需要补录的样本会标记为待复核。"}
          </p>
        </details>

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.72fr)]">
          <div className="space-y-5">
            <fieldset>
              <legend className="text-sm font-semibold">OK 判定层级</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {OK_GRANULARITY_OPTIONS.map((option) => (
                  <PolicyOption
                    key={String(option.splitOk)}
                    name="ok-granularity"
                    checked={draft.split_ok === option.splitOk}
                    title={option.title}
                    description={option.description}
                    onChange={() => onChange({ ...draft, split_ok: option.splitOk })}
                  />
                ))}
              </div>
            </fieldset>

            <fieldset>
              <legend className="text-sm font-semibold">NG 分类方式</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {NG_GROUPING_OPTIONS.map((option) => (
                  <PolicyOption
                    key={option.value}
                    name="ng-granularity"
                    checked={draft.ng_grouping === option.value}
                    title={option.title}
                    description={option.description}
                    onChange={() => onChange({ ...draft, ng_grouping: option.value })}
                  />
                ))}
              </div>
            </fieldset>
          </div>

          <div className="rounded-xl border border-line bg-gray-950 p-4 text-gray-200">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-400">将生成的目录结构</div>
            <div className="mt-4 font-mono text-sm leading-6">
              <div className="font-bold text-white">ok/</div>
              {draft.split_ok && (
                <div className="ml-2 mt-1 border-l border-white/20 pl-3 text-gray-300">
                  <div>clear/</div>
                  <div>borderline/</div>
                </div>
              )}
              <div className="mt-5 font-bold text-white">ng/</div>
              {draft.ng_grouping !== "none" && (
                <div className="ml-2 mt-1 border-l border-white/20 pl-3 text-gray-300">
                  {draft.ng_grouping === "defect_type" && <div>&#123;defect_type&#125;/</div>}
                  {draft.ng_grouping === "severity" && <><div>mild/</div><div>moderate/</div><div>severe/</div></>}
                  {draft.ng_grouping === "defect_type_and_severity" && (
                    <><div>&#123;defect_type&#125;/</div><div className="pl-4">&#123;severity&#125;/</div></>
                  )}
                </div>
              )}
            </div>
            {stats && Object.keys(stats.by_export_bucket).length > 0 && (
              <div className="mt-4 border-t border-white/10 pt-3">
                <div className="text-xs text-gray-400">当前已保存结果</div>
                <div className="mt-2 space-y-1 text-xs">
                  {Object.entries(stats.by_export_bucket).map(([bucket, count]) => (
                    <div key={bucket} className="flex justify-between gap-3">
                      <span className="truncate">{bucket}/</span><span>{count} 张</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {needsConfirmation && impact && (
          <div role="alert" className="mt-5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <div className="flex items-start gap-2 font-semibold">
              <CircleAlert size={18} className="mt-0.5 shrink-0" />
              修改会影响 {impact.requires_review_count} 张已有判定
            </div>
            <ul className="mt-2 list-disc space-y-1 pl-6 text-xs leading-5">
              {impact.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              {impact.missing_ok_grade_count > 0 && (
                <li>{impact.missing_ok_grade_count} 张 OK 需要补选“完全 / 临界”。</li>
              )}
              {impact.missing_defect_type_count > 0 && (
                <li>{impact.missing_defect_type_count} 张 NG 需要补选缺陷类别。</li>
              )}
              {impact.missing_severity_count > 0 && (
                <li>{impact.missing_severity_count} 张 NG 需要补选严重程度。</li>
              )}
            </ul>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <details className="group max-w-xl text-xs text-gray-500">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium text-gray-600">
              <Info size={14} /> 原始图片不会被修改
              <ChevronDown size={14} className="transition-transform group-open:rotate-180" />
            </summary>
            <p className="mt-1 pl-5 leading-5">仅更新 SQLite 元数据，不移动、重命名或删除原始图片。</p>
          </details>
          <div className="flex gap-2">
            {!firstRun && (
              <button type="button" onClick={onCancel} className="min-h-10 rounded-lg border border-line px-4 text-sm font-medium">
                取消
              </button>
            )}
            <button
              type="button"
              onClick={onSubmit}
              disabled={saving}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white disabled:opacity-50"
            >
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
              {needsConfirmation
                ? "确认修改并标记待复核"
                : firstRun ? "使用此配置开始" : "查看影响并保存"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
