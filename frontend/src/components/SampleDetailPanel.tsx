import { Save, Trash2, Wrench, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getSampleFileUrl, getSamplePreview } from "../api/client";
import type { Sample, SamplePreview, Tag } from "../types/dataset";
import TagEditor from "./TagEditor";

interface SampleDetailPanelProps {
  sample: Sample | null;
  availableTags: Tag[];
  saving: boolean;
  repairing: boolean;
  deleting: boolean;
  onClose: () => void;
  onSave: (payload: { split: string | null; notes: string | null; tags: string[] }) => Promise<void>;
  onRepair: (filePath: string) => Promise<void>;
  onDelete: () => Promise<void>;
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

export default function SampleDetailPanel({
  sample,
  availableTags,
  saving,
  repairing,
  deleting,
  onClose,
  onSave,
  onRepair,
  onDelete
}: SampleDetailPanelProps) {
  const [split, setSplit] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [repairPath, setRepairPath] = useState("");
  const [preview, setPreview] = useState<SamplePreview | null>(null);

  useEffect(() => {
    setSplit(sample?.split ?? "");
    setNotes(sample?.notes ?? "");
    setTags(sample?.tags.map((tag) => tag.name) ?? []);
    setRepairPath(sample?.absolute_path ?? "");
    setPreview(null);
    if (sample) {
      void getSamplePreview(sample.id).then(setPreview).catch(() => {
        setPreview({
          sample_id: sample.id,
          file_type: sample.file_type,
          filename: sample.filename,
          file_url: null,
          columns: [],
          rows: [],
          preview_row_count: 0,
          error: "预览加载失败"
        });
      });
    }
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
          {sample.file_status === "missing" ? (
            <div className="flex h-40 items-center justify-center text-sm text-amber-700">文件缺失</div>
          ) : sample.file_type === "image" ? (
            <img src={getSampleFileUrl(sample.id)} alt={sample.filename} className="max-h-72 w-full object-contain" />
          ) : sample.file_type === "video" ? (
            <video src={getSampleFileUrl(sample.id)} controls className="max-h-72 w-full bg-black" />
          ) : sample.file_type === "table" && preview?.rows.length ? (
            <div className="max-h-72 overflow-auto bg-white">
              <table className="min-w-full text-left text-xs">
                <thead className="sticky top-0 bg-gray-50 text-gray-500">
                  <tr>
                    {preview.columns.map((column) => (
                      <th key={column} className="border-b border-line px-3 py-2 font-medium">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className="border-b border-line last:border-0">
                      {preview.columns.map((column) => (
                        <td key={column} className="max-w-44 truncate px-3 py-2 text-gray-700">
                          {row[column]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-gray-500">
              {preview?.error || sample.extension.toUpperCase()}
            </div>
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
          <div className="rounded-lg border border-line px-3 py-2">
            <dt className="text-gray-500">状态</dt>
            <dd className="mt-1 font-medium text-ink">{sample.file_status}</dd>
          </div>
          <div className="rounded-lg border border-line px-3 py-2">
            <dt className="text-gray-500">划分</dt>
            <dd className="mt-1 font-medium text-ink">{sample.split || "未设置"}</dd>
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
          {Object.keys(sample.metadata).length > 0 && (
            <div className="rounded-lg border border-line p-3">
              <div className="text-sm font-medium text-gray-700">元数据</div>
              <dl className="mt-2 space-y-1 text-sm">
                {Object.entries(sample.metadata).map(([key, value]) => (
                  <div key={key} className="grid grid-cols-[110px_1fr] gap-2">
                    <dt className="truncate text-gray-500">{key}</dt>
                    <dd className="min-w-0 break-all text-gray-800">{String(value ?? "")}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
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
          {(sample.file_status === "missing" || sample.file_status === "permission_denied") && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <div className="text-sm font-medium text-amber-800">重新定位缺失文件</div>
              <div className="mt-2 flex gap-2">
                <input
                  value={repairPath}
                  onChange={(event) => setRepairPath(event.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-amber-700"
                  placeholder="D:/dataset/new-path/sample.jpg"
                />
                <button
                  type="button"
                  onClick={() => onRepair(repairPath.trim())}
                  disabled={repairing || !repairPath.trim()}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-amber-700 px-3 py-2 text-sm font-medium text-white hover:bg-amber-800 disabled:cursor-not-allowed disabled:bg-amber-200"
                >
                  <Wrench size={16} />
                  {repairing ? "修复中" : "修复"}
                </button>
              </div>
              <div className="mt-2 text-xs text-amber-800">只更新数据库中的路径和文件元数据，不移动或删除本地文件。</div>
            </div>
          )}
          <div className="block">
            <div className="text-sm font-medium text-gray-700">标签</div>
            <div className="mt-2">
              <TagEditor tags={tags} options={availableTags} onChange={setTags} />
            </div>
          </div>
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
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting || saving || repairing}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 px-3 py-2.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-red-200"
          >
            <Trash2 size={17} />
            {deleting ? "删除中" : "删记录"}
          </button>
          <button
            type="button"
            onClick={() => onSave({ split: split || null, notes: notes || null, tags })}
            disabled={saving || deleting || repairing}
            className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            <Save size={17} />
            {saving ? "保存中" : "保存更改"}
          </button>
        </div>
      </div>
    </aside>
  );
}
