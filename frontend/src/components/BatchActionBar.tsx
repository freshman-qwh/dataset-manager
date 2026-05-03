import { CheckSquare, Trash2, Tags } from "lucide-react";
import { useState } from "react";

interface BatchActionBarProps {
  selectedCount: number;
  busy: boolean;
  deleting: boolean;
  onApply: (payload: { split: string | null; addTags: string[] }) => Promise<void>;
  onDelete: () => Promise<void>;
  onClear: () => void;
}

function parseTags(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function BatchActionBar({ selectedCount, busy, deleting, onApply, onDelete, onClear }: BatchActionBarProps) {
  const [split, setSplit] = useState("");
  const [tags, setTags] = useState("");

  if (selectedCount === 0) {
    return null;
  }

  async function handleApply() {
    await onApply({ split: split || null, addTags: parseTags(tags) });
    setSplit("");
    setTags("");
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-white p-3 shadow-sm lg:flex-row lg:items-center">
      <div className="inline-flex items-center gap-2 text-sm font-medium text-ink">
        <CheckSquare size={17} />
        已选择 {selectedCount} 项
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row">
        <select
          value={split}
          onChange={(event) => setSplit(event.target.value)}
          className="rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-36"
        >
          <option value="">不改划分</option>
          <option value="train">train</option>
          <option value="val">val</option>
          <option value="test">test</option>
        </select>
        <label className="relative min-w-0 flex-1">
          <Tags className="pointer-events-none absolute left-3 top-2.5 text-gray-400" size={17} />
          <input
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            className="w-full rounded-lg border border-line py-2 pl-10 pr-3 text-sm outline-none transition focus:border-gray-900"
            placeholder="批量添加标签，逗号分隔"
          />
        </label>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onClear}
          className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          清空
        </button>
        <button
          type="button"
          onClick={handleApply}
          disabled={busy || deleting || (!split && parseTags(tags).length === 0)}
          className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {busy ? "应用中" : "应用"}
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={busy || deleting}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-red-200"
        >
          <Trash2 size={16} />
          {deleting ? "删除中" : "删除记录"}
        </button>
      </div>
    </div>
  );
}
