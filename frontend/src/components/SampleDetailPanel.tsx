import { Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getSampleFileUrl } from "../api/client";
import type { Sample } from "../types/dataset";
import TagEditor from "./TagEditor";

interface SampleDetailPanelProps {
  sample: Sample | null;
  saving: boolean;
  onClose: () => void;
  onSave: (payload: { split: string | null; notes: string | null; tags: string[] }) => Promise<void>;
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

export default function SampleDetailPanel({ sample, saving, onClose, onSave }: SampleDetailPanelProps) {
  const [split, setSplit] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState<string[]>([]);

  useEffect(() => {
    setSplit(sample?.split ?? "");
    setNotes(sample?.notes ?? "");
    setTags(sample?.tags.map((tag) => tag.name) ?? []);
  }, [sample]);

  const shortHash = useMemo(() => sample?.file_hash.slice(0, 16), [sample]);

  if (!sample) {
    return null;
  }

  return (
    <aside className="fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l border-line bg-white shadow-soft">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 className="min-w-0 truncate text-base font-semibold text-ink">{sample.filename}</h2>
        <button
          type="button"
          title="关闭"
          onClick={onClose}
          className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
        >
          <X size={18} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <div className="overflow-hidden rounded-lg border border-line bg-gray-50">
          {sample.file_type === "image" ? (
            <img src={getSampleFileUrl(sample.id)} alt={sample.filename} className="max-h-72 w-full object-contain" />
          ) : sample.file_type === "video" ? (
            <video src={getSampleFileUrl(sample.id)} controls className="max-h-72 w-full bg-black" />
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-gray-500">{sample.extension.toUpperCase()}</div>
          )}
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-lg border border-line px-3 py-2">
            <dt className="text-gray-500">类型</dt>
            <dd className="mt-1 font-medium text-ink">{sample.file_type}</dd>
          </div>
          <div className="rounded-lg border border-line px-3 py-2">
            <dt className="text-gray-500">大小</dt>
            <dd className="mt-1 font-medium text-ink">{formatBytes(sample.file_size)}</dd>
          </div>
          <div className="col-span-2 rounded-lg border border-line px-3 py-2">
            <dt className="text-gray-500">相对路径</dt>
            <dd className="mt-1 break-all font-medium text-ink">{sample.relative_path}</dd>
          </div>
          <div className="col-span-2 rounded-lg border border-line px-3 py-2">
            <dt className="text-gray-500">SHA256</dt>
            <dd className="mt-1 break-all font-mono text-xs text-ink">{shortHash}...</dd>
          </div>
        </dl>

        <div className="mt-5 space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">划分</span>
            <select
              value={split}
              onChange={(event) => setSplit(event.target.value)}
              className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            >
              <option value="">未设置</option>
              <option value="train">train</option>
              <option value="val">val</option>
              <option value="test">test</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">标签</span>
            <div className="mt-2">
              <TagEditor tags={tags} onChange={setTags} />
            </div>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">备注</span>
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="mt-2 min-h-28 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            />
          </label>
        </div>
      </div>
      <div className="border-t border-line px-5 py-4">
        <button
          type="button"
          onClick={() => onSave({ split: split || null, notes: notes || null, tags })}
          disabled={saving}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          <Save size={17} />
          {saving ? "保存中" : "保存更改"}
        </button>
      </div>
    </aside>
  );
}
