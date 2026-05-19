import { AlertTriangle, CheckSquare, Database, FileText, Image as ImageIcon, PencilLine, Square, Video } from "lucide-react";

import { getSampleFileUrl } from "../api/client";
import type { Sample } from "../types/dataset";
import { tagChipStyle } from "../utils/colors";

interface SampleGridProps {
  samples: Sample[];
  selectedId?: number;
  selectedSampleIds: Set<number>;
  onSelect: (sample: Sample) => void;
  onToggleSelect: (sampleId: number) => void;
  onAnnotate?: (sample: Sample) => void;
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function FilePreview({ sample }: { sample: Sample }) {
  if (sample.file_status === "missing") {
    return (
      <div className="flex h-full w-full items-center justify-center bg-amber-50 text-amber-600">
        <AlertTriangle size={34} />
      </div>
    );
  }

  if (sample.file_type === "image") {
    return (
      <img
        src={getSampleFileUrl(sample.id)}
        alt={sample.filename}
        className="h-full w-full object-cover"
        loading="lazy"
      />
    );
  }

  if (sample.file_type === "video") {
    return (
      <video
        src={getSampleFileUrl(sample.id)}
        className="h-full w-full object-cover"
        muted
        preload="metadata"
      />
    );
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-gray-50 text-gray-400">
      {sample.file_type === "table" ? <FileText size={34} /> : <Database size={34} />}
    </div>
  );
}

function statusLabel(status: string): string {
  if (status === "missing") {
    return "缺失";
  }
  if (status === "permission_denied") {
    return "无权限";
  }
  return "正常";
}

export default function SampleGrid({
  samples,
  selectedId,
  selectedSampleIds,
  onSelect,
  onToggleSelect,
  onAnnotate
}: SampleGridProps) {
  if (samples.length === 0) {
    return (
      <div className="flex min-h-72 items-center justify-center rounded-lg border border-dashed border-line bg-white text-sm text-gray-500">
        暂无样本
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {samples.map((sample) => (
        <div
          key={sample.id}
          className={`overflow-hidden rounded-lg border bg-white text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-soft ${
            selectedId === sample.id ? "border-gray-900" : "border-line"
          }`}
        >
          <div className="relative">
            <button
              type="button"
              title={selectedSampleIds.has(sample.id) ? "取消选择" : "选择样本"}
              onClick={() => onToggleSelect(sample.id)}
              className="absolute left-2 top-2 z-10 rounded-lg bg-white/90 p-1.5 text-gray-700 shadow-sm hover:bg-white"
            >
              {selectedSampleIds.has(sample.id) ? <CheckSquare size={17} /> : <Square size={17} />}
            </button>
            {sample.file_status !== "normal" && (
              <span className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700 shadow-sm">
                <AlertTriangle size={13} />
                {statusLabel(sample.file_status)}
              </span>
            )}
            <button type="button" onClick={() => onSelect(sample)} className="block w-full text-left">
              <div className="aspect-[4/3] overflow-hidden bg-gray-50">
                <FilePreview sample={sample} />
              </div>
            </button>
          </div>
          <div className="space-y-2 p-3">
            <div className="flex items-start gap-2">
              <button type="button" onClick={() => onSelect(sample)} className="min-w-0 flex-1 text-left">
                <div className="flex items-center gap-2">
                  {sample.file_type === "image" ? (
                    <ImageIcon className="shrink-0 text-gray-400" size={16} />
                  ) : sample.file_type === "video" ? (
                    <Video className="shrink-0 text-gray-400" size={16} />
                  ) : (
                    <FileText className="shrink-0 text-gray-400" size={16} />
                  )}
                  <div className="min-w-0 truncate text-sm font-medium text-ink">{sample.filename}</div>
                </div>
                <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 text-xs text-gray-500">
                  <span className="min-w-0 truncate">{sample.extension || sample.file_type}</span>
                  <span className="shrink-0 whitespace-nowrap tabular-nums">{formatBytes(sample.file_size)}</span>
                </div>
              </button>
              {onAnnotate && sample.file_type === "image" && sample.file_status === "normal" && (
                <button
                  type="button"
                  title="打开标注工作区"
                  onClick={() => onAnnotate(sample)}
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-white text-gray-800 shadow-sm hover:bg-gray-50"
                >
                  <PencilLine size={17} />
                </button>
              )}
            </div>
            {(sample.split || sample.tags.length > 0) && (
              <div className="flex flex-wrap gap-1.5">
                {sample.split && (
                  <span className="rounded-md border border-gray-900 bg-gray-900 px-2 py-0.5 text-xs font-medium text-white">
                    {sample.split}
                  </span>
                )}
                {sample.tags.slice(0, 3).map((tagItem) => (
                  <span
                    key={tagItem.id}
                    className="rounded-md border border-line bg-gray-50 px-2 py-0.5 text-xs text-gray-600"
                    style={tagChipStyle(tagItem.color)}
                  >
                    {tagItem.name}
                  </span>
                ))}
                {sample.tags.length > 3 && (
                  <span className="rounded-md border border-line bg-gray-50 px-2 py-0.5 text-xs text-gray-500">
                    +{sample.tags.length - 3}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
