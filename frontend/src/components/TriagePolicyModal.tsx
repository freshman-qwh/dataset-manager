import { Check, CircleAlert, Loader2 } from "lucide-react";

import type {
  NgGrouping,
  TriagePolicyImpactPreview,
  TriagePolicyValues,
  TriageStats
} from "../types/triage";
import Modal from "./Modal";

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
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3">
          <p className="text-sm font-semibold text-blue-950">
            {firstRun ? "先确定要记录到什么粒度，再开始判定。" : "这里只修改后续分拣规则，不会立即删除已有判定。"}
          </p>
          <p className="mt-1 text-xs leading-5 text-blue-800">
            新用户建议使用“统一 OK + NG 不细分”；需要研究级分析时再开启细分。
          </p>
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.72fr)]">
          <div className="space-y-5">
            <fieldset>
              <legend className="text-sm font-semibold">合格样本怎么记</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <label className={`cursor-pointer rounded-xl border p-3 ${!draft.split_ok ? "border-gray-900 bg-gray-50" : "border-line"}`}>
                  <input
                    type="radio"
                    name="ok-granularity"
                    checked={!draft.split_ok}
                    onChange={() => onChange({ ...draft, split_ok: false })}
                  />
                  <span className="ml-2 text-sm font-semibold">统一 OK（推荐）</span>
                  <span className="mt-1 block pl-6 text-xs leading-5 text-gray-500">只判断合格，导出到 ok/</span>
                </label>
                <label className={`cursor-pointer rounded-xl border p-3 ${draft.split_ok ? "border-gray-900 bg-gray-50" : "border-line"}`}>
                  <input
                    type="radio"
                    name="ok-granularity"
                    checked={draft.split_ok}
                    onChange={() => onChange({ ...draft, split_ok: true })}
                  />
                  <span className="ml-2 text-sm font-semibold">细分完全 / 临界 OK</span>
                  <span className="mt-1 block pl-6 text-xs leading-5 text-gray-500">适合需要复核边界样本的研究流程</span>
                </label>
              </div>
            </fieldset>

            <fieldset>
              <legend className="text-sm font-semibold">异常样本怎么记</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {NG_GROUPING_OPTIONS.map((option) => (
                  <label key={option.value} className={`cursor-pointer rounded-xl border p-3 ${draft.ng_grouping === option.value ? "border-gray-900 bg-gray-50" : "border-line"}`}>
                    <input
                      type="radio"
                      name="ng-granularity"
                      checked={draft.ng_grouping === option.value}
                      onChange={() => onChange({ ...draft, ng_grouping: option.value })}
                    />
                    <span className="ml-2 text-sm font-semibold">{option.title}</span>
                    <span className="mt-1 block pl-6 text-xs leading-5 text-gray-500">{option.description}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          <div className="rounded-xl border border-line bg-gray-950 p-4 text-gray-200">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-400">将生成的目录结构</div>
            <div className="mt-3 space-y-1 font-mono text-sm leading-6">
              {draft.split_ok ? <><div>ok/clear/</div><div>ok/borderline/</div></> : <div>ok/</div>}
              {draft.ng_grouping === "none" && <div>ng/</div>}
              {draft.ng_grouping === "defect_type" && <div>ng/&#123;defect_type&#125;/</div>}
              {draft.ng_grouping === "severity" && <div>ng/&#123;mild|moderate|severe&#125;/</div>}
              {draft.ng_grouping === "defect_type_and_severity" && <div>ng/&#123;defect_type&#125;/&#123;severity&#125;/</div>}
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
          <p className="text-xs text-gray-500">
            修改配置只写入 SQLite 元数据，不移动、重命名或删除原始图片。
          </p>
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
