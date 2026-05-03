import { AlertTriangle, CheckCircle2, GitBranch, Search, Tags, Wrench } from "lucide-react";

import type { DatasetStats, DuplicateReport } from "../types/dataset";
import Modal from "./Modal";

interface DatasetQualityModalProps {
  open: boolean;
  stats: DatasetStats | null;
  duplicateReport: DuplicateReport | null;
  onClose: () => void;
  onFilterMissing: () => void;
  onFilterUnassigned: () => void;
  onFilterUnlabeled: () => void;
  onOpenRepairMissing: () => void;
  onOpenSplitPlan: () => void;
}

function statusClass(level: "ok" | "warn" | "danger"): string {
  if (level === "danger") {
    return "border-red-200 bg-red-50 text-red-700";
  }
  if (level === "warn") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-700";
}

function splitStatusClass(hasIssue: boolean): string {
  return hasIssue ? "border-blue-200 bg-blue-50 text-blue-800" : "border-sky-200 bg-sky-50 text-sky-700";
}

export default function DatasetQualityModal({
  open,
  stats,
  duplicateReport,
  onClose,
  onFilterMissing,
  onFilterUnassigned,
  onFilterUnlabeled,
  onOpenRepairMissing,
  onOpenSplitPlan
}: DatasetQualityModalProps) {
  const sampleCount = stats?.sample_count ?? 0;
  const missingCount = (stats?.by_status.missing ?? 0) + (stats?.by_status.permission_denied ?? 0);
  const duplicateGroups = stats?.duplicate_groups ?? 0;
  const duplicateSamples = stats?.duplicate_samples ?? 0;
  const unassigned = stats?.by_split.unassigned ?? 0;
  const train = stats?.by_split.train ?? 0;
  const val = stats?.by_split.val ?? 0;
  const test = stats?.by_split.test ?? 0;
  const unlabeled = stats?.unlabeled_samples ?? 0;
  const hasAnySplit = train + val + test > 0;
  const missingTest = hasAnySplit && test === 0;
  const allClear = sampleCount > 0 && missingCount === 0 && duplicateGroups === 0 && unassigned === 0 && unlabeled === 0 && !missingTest;

  return (
    <Modal open={open} title="数据集体检" onClose={onClose}>
      <div className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <div className={`rounded-lg border p-3 text-sm ${allClear ? statusClass("ok") : statusClass("warn")}`}>
          <div className="flex items-start gap-2">
            {allClear ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
            <div>
              <div className="font-medium">{allClear ? "当前没有明显阻塞项" : "建议先处理影响训练可靠性的项目"}</div>
              <div className="mt-1 text-xs opacity-90">这里检查文件可用性、重复样本、标签覆盖和 train/val/test 划分，不做逐样本人工审核。</div>
            </div>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className={`rounded-lg border p-3 ${statusClass(missingCount > 0 ? "danger" : "ok")}`}>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Wrench size={17} />
              文件状态
            </div>
            <div className="mt-2 text-2xl font-semibold">{missingCount}</div>
            <div className="text-xs">缺失或无权限样本</div>
            {missingCount > 0 && (
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={onFilterMissing} className="rounded-md bg-white px-2 py-1 text-xs font-medium shadow-sm">
                  查看
                </button>
                <button type="button" onClick={onOpenRepairMissing} className="rounded-md bg-white px-2 py-1 text-xs font-medium shadow-sm">
                  修复
                </button>
              </div>
            )}
          </div>

          <div className={`rounded-lg border p-3 ${statusClass(duplicateGroups > 0 ? "warn" : "ok")}`}>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Search size={17} />
              重复样本
            </div>
            <div className="mt-2 text-2xl font-semibold">{duplicateGroups}</div>
            <div className="text-xs">重复组，涉及 {duplicateSamples} 个样本</div>
          </div>

          <div className={`rounded-lg border p-3 ${statusClass(unlabeled > 0 ? "warn" : "ok")}`}>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Tags size={17} />
              标签覆盖
            </div>
            <div className="mt-2 text-2xl font-semibold">{unlabeled}</div>
            <div className="text-xs">未挂任何标签的样本</div>
            {unlabeled > 0 && (
              <button type="button" onClick={onFilterUnlabeled} className="mt-3 rounded-md bg-white px-2 py-1 text-xs font-medium shadow-sm">
                查看未标注
              </button>
            )}
          </div>

          <div className={`rounded-lg border p-3 ${splitStatusClass(unassigned > 0 || missingTest)}`}>
            <div className="flex items-center gap-2 text-sm font-medium">
              <GitBranch size={17} />
              数据划分
            </div>
            <div className="mt-2 text-sm">train {train} / val {val} / test {test}</div>
            <div className="mt-1 text-xs">未划分 {unassigned} 个{missingTest ? "，当前没有 test 集" : ""}</div>
            {(unassigned > 0 || missingTest) && (
              <div className="mt-3 flex gap-2">
                {unassigned > 0 && (
                  <button type="button" onClick={onFilterUnassigned} className="rounded-md bg-white px-2 py-1 text-xs font-medium shadow-sm">
                    查看
                  </button>
                )}
                <button type="button" onClick={onOpenSplitPlan} className="rounded-md bg-white px-2 py-1 text-xs font-medium shadow-sm">
                  划分
                </button>
              </div>
            )}
          </div>
        </div>

        {duplicateReport && duplicateReport.group_count > 0 && (
          <div className="rounded-lg border border-line p-3">
            <div className="text-sm font-medium text-gray-700">重复样本示例</div>
            <div className="mt-2 max-h-28 space-y-1 overflow-auto text-xs text-gray-600">
              {duplicateReport.groups.slice(0, 5).map((group) => (
                <div key={group.file_hash} className="truncate">
                  {group.file_hash.slice(0, 12)}...：{group.samples.map((sample) => sample.relative_path).join(" / ")}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex justify-end">
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            关闭
          </button>
        </div>
      </div>
    </Modal>
  );
}
