import type { Sample } from "../types/dataset";
import LocalBrowseThumbnail from "./LocalBrowseThumbnail";
import { browseFileSize } from "./LocalBrowsePreview";

interface Props {
  sample: Sample;
  selected: boolean;
  caption: string;
  thumbnailRevision: number;
  deferOriginal: boolean;
  onSelect: () => void;
  onPreview: () => void;
}

export default function BrowseFileCard({ sample, selected, caption, thumbnailRevision, deferOriginal, onSelect, onPreview }: Props) {
  return <div className={`relative min-w-0 overflow-hidden rounded-lg border bg-white ${selected ? "border-gray-900 ring-1 ring-gray-900" : "border-line"}`}>
    <input type="checkbox" aria-label={`选择 ${sample.filename}`} checked={selected} onChange={onSelect} className="absolute left-2 top-2 z-10 h-4 w-4 accent-gray-900" />
    <button type="button" aria-label={`预览 ${sample.filename}`} onClick={onPreview} className="block w-full min-w-0 text-left hover:bg-gray-50">
      <span className="relative block aspect-[4/3] bg-gray-100/70 p-2"><LocalBrowseThumbnail key={`${sample.id}:${sample.file_hash}:${thumbnailRevision}`} sampleId={sample.id} name={sample.filename} fileType={sample.file_type} fileStatus={sample.file_status} contentHash={sample.file_hash} deferOriginal={deferOriginal} />
        {sample.file_status !== "normal" && <span className="absolute bottom-2 right-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">{sample.file_status === "missing" ? "缺失" : "不可用"}</span>}
      </span>
      <span className="block min-w-0 p-3"><span className="block truncate text-xs font-medium text-gray-700" title={sample.filename}>{sample.filename}</span><span className="mt-1 block truncate text-[11px] text-gray-400" title={sample.absolute_path}>{caption || browseFileSize(sample.file_size)}</span>
        {(sample.official_split || sample.mask_path) && <span className="mt-1 flex flex-wrap gap-2 text-[10px] text-gray-500">{sample.official_split && <span>官方 {sample.official_split}</span>}{sample.mask_path && <span>Mask</span>}</span>}
      </span>
    </button>
  </div>;
}
