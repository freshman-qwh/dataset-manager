import { AlertTriangle, Copy } from "lucide-react";

import type { DuplicateReport } from "../types/dataset";
import Modal from "./Modal";

interface DatasetIssueModalProps {
  issue: "missing" | "duplicate" | null;
  missingCount: number;
  permissionDeniedCount: number;
  duplicateGroupCount: number;
  duplicateSampleCount: number;
  duplicateReport: DuplicateReport | null;
  onClose: () => void;
  onFilterMissing: () => void;
  onFilterPermissionDenied: () => void;
  onFilterDuplicates: () => void;
  onRepairMissing: () => void;
}

export default function DatasetIssueModal({
  issue,
  missingCount,
  permissionDeniedCount,
  duplicateGroupCount,
  duplicateSampleCount,
  duplicateReport,
  onClose,
  onFilterMissing,
  onFilterPermissionDenied,
  onFilterDuplicates,
  onRepairMissing
}: DatasetIssueModalProps) {
  if (!issue) {
    return null;
  }

  if (issue === "missing") {
    return (
      <Modal open title="缺失文件" onClose={onClose}>
        <div className="space-y-4 px-5 py-5">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle size={17} />
              文件可用性异常
            </div>
            <div className="mt-2">缺失 {missingCount} 个，无权限 {permissionDeniedCount} 个。</div>
          </div>
          <div className="flex flex-wrap gap-2">
            {missingCount > 0 && (
              <button type="button" onClick={onFilterMissing} className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                查看缺失
              </button>
            )}
            {permissionDeniedCount > 0 && (
              <button type="button" onClick={onFilterPermissionDenied} className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                查看无权限
              </button>
            )}
            {(missingCount > 0 || permissionDeniedCount > 0) && (
              <button type="button" onClick={onRepairMissing} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
                修复缺失
              </button>
            )}
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal open title="重复样本" onClose={onClose}>
      <div className="space-y-4 px-5 py-5">
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <div className="flex items-center gap-2 font-medium">
            <Copy size={17} />
            发现 {duplicateGroupCount} 组重复，涉及 {duplicateSampleCount} 个样本
          </div>
        </div>
        {duplicateReport && duplicateReport.group_count > 0 && (
          <div className="max-h-44 space-y-1 overflow-auto rounded-lg border border-line p-3 text-xs text-gray-600">
            {duplicateReport.groups.slice(0, 8).map((group) => (
              <div key={group.file_hash} className="truncate">
                {group.file_hash.slice(0, 12)}...：{group.samples.map((sample) => sample.relative_path).join(" / ")}
              </div>
            ))}
          </div>
        )}
        {duplicateSampleCount > 0 ? (
          <button type="button" onClick={onFilterDuplicates} className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            查看重复样本
          </button>
        ) : (
          <div className="text-sm text-gray-500">当前没有重复样本。</div>
        )}
      </div>
    </Modal>
  );
}
