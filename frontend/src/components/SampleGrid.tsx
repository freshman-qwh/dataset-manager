import { Database, FileText, Image as ImageIcon, Video } from "lucide-react";

import { getSampleFileUrl } from "../api/client";
import type { Sample } from "../types/dataset";

interface SampleGridProps {
  samples: Sample[];
  selectedId?: number;
  onSelect: (sample: Sample) => void;
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

export default function SampleGrid({ samples, selectedId, onSelect }: SampleGridProps) {
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
        <button
          type="button"
          key={sample.id}
          onClick={() => onSelect(sample)}
          className={`overflow-hidden rounded-lg border bg-white text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-soft ${
            selectedId === sample.id ? "border-gray-900" : "border-line"
          }`}
        >
          <div className="aspect-[4/3] overflow-hidden bg-gray-50">
            <FilePreview sample={sample} />
          </div>
          <div className="space-y-2 p-3">
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
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>{sample.extension || sample.file_type}</span>
              <span>{formatBytes(sample.file_size)}</span>
            </div>
            {sample.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {sample.tags.slice(0, 3).map((tagItem) => (
                  <span
                    key={tagItem.id}
                    className="rounded-md border border-line bg-gray-50 px-2 py-0.5 text-xs text-gray-600"
                  >
                    {tagItem.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}
