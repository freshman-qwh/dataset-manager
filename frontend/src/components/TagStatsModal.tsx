import { Tags } from "lucide-react";

import type { DatasetStats, Tag } from "../types/dataset";
import { tagChipStyle } from "../utils/colors";
import Modal from "./Modal";

interface TagStatsModalProps {
  open: boolean;
  stats: DatasetStats | null;
  tags: Tag[];
  onClose: () => void;
  onManage: () => void;
  onFilterTag: (tagName: string) => void;
  onFilterUnlabeled: () => void;
}

export default function TagStatsModal({
  open,
  stats,
  tags,
  onClose,
  onManage,
  onFilterTag,
  onFilterUnlabeled
}: TagStatsModalProps) {
  const tagByName = new Map(tags.map((tag) => [tag.name, tag]));
  const rows = Object.entries(stats?.tag_counts ?? {}).sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
  const totalTaggedHits = rows.reduce((total, [, count]) => total + count, 0);
  const sampleCount = stats?.sample_count ?? 0;
  const unlabeled = stats?.unlabeled_samples ?? 0;

  return (
    <Modal open={open} title="标签统计" onClose={onClose}>
      <div className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <div className="grid gap-3 text-sm sm:grid-cols-3">
          <div className="rounded-lg border border-line p-3">
            <div className="text-xs text-gray-500">标签种类</div>
            <div className="mt-1 text-2xl font-semibold text-ink">{rows.length}</div>
          </div>
          <div className="rounded-lg border border-line p-3">
            <div className="text-xs text-gray-500">标签命中</div>
            <div className="mt-1 text-2xl font-semibold text-ink">{totalTaggedHits}</div>
          </div>
          <div className="rounded-lg border border-line p-3">
            <div className="text-xs text-gray-500">未标注样本</div>
            <div className="mt-1 text-2xl font-semibold text-ink">{unlabeled}</div>
          </div>
        </div>

        <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-800">
          多标签样本会同时计入每个标签，因此标签命中数可能大于样本总数 {sampleCount}。
        </div>

        {rows.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-gray-500">
            当前没有已使用标签
          </div>
        ) : (
          <div className="space-y-2">
            {rows.map(([tagName, count]) => {
              const tag = tagByName.get(tagName);
              const percent = sampleCount > 0 ? Math.round((count / sampleCount) * 100) : 0;
              return (
                <div key={tagName} className="rounded-lg border border-line p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <span className="rounded-md border border-line px-2 py-0.5 text-xs font-medium" style={tagChipStyle(tag?.color)}>
                        {tagName}
                      </span>
                      <div className="mt-1 text-xs text-gray-500">{count} 个样本命中，约 {percent}%</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onFilterTag(tagName)}
                      className="rounded-lg border border-line px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      查看
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          {unlabeled > 0 && (
            <button type="button" onClick={onFilterUnlabeled} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              查看未标注
            </button>
          )}
          <button type="button" onClick={onManage} className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800">
            <Tags size={16} />
            管理标签
          </button>
        </div>
      </div>
    </Modal>
  );
}
