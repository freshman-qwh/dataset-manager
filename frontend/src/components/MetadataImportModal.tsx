import { FormEvent, useState } from "react";
import axios from "axios";

import { importMetadata } from "../api/client";
import type { MetadataImportResult } from "../types/dataset";
import Modal from "./Modal";

interface MetadataImportModalProps {
  datasetId: number;
  open: boolean;
  onClose: () => void;
  onImported: () => Promise<void>;
}

export default function MetadataImportModal({ datasetId, open, onClose, onImported }: MetadataImportModalProps) {
  const [filePath, setFilePath] = useState("");
  const [matchBy, setMatchBy] = useState("relative_path");
  const [tagColumn, setTagColumn] = useState("tags");
  const [replaceTags, setReplaceTags] = useState(false);
  const [result, setResult] = useState<MetadataImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!filePath.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const nextResult = await importMetadata(datasetId, {
        file_path: filePath.trim(),
        match_by: matchBy,
        tag_column: tagColumn.trim() || "tags",
        replace_tags: replaceTags
      });
      setResult(nextResult);
      await onImported();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title="导入元数据" onClose={onClose}>
      <form onSubmit={handleSubmit} className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">CSV / JSON 文件路径 *</span>
          <input
            value={filePath}
            onChange={(event) => setFilePath(event.target.value)}
            className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            placeholder="D:/metadata/sample_labels.csv"
          />
          <span className="mt-1 block text-xs text-gray-500">这里填写后端能读取到的本机绝对路径，不是浏览器上传。</span>
        </label>
        <div className="rounded-lg border border-line bg-gray-50 p-3 text-xs text-gray-600">
          <div className="font-medium text-gray-700">CSV 示例</div>
          <pre className="mt-2 overflow-auto rounded-md bg-white p-2">{`relative_path,tags,split,notes,quality
images/a.png,"cat;review",train,"good sample",high`}</pre>
          <div className="mt-3 font-medium text-gray-700">JSON 示例</div>
          <pre className="mt-2 overflow-auto rounded-md bg-white p-2">{`[
  {
    "relative_path": "images/a.png",
    "tags": ["cat", "review"],
    "split": "train",
    "notes": "good sample",
    "quality": "high"
  }
]`}</pre>
          <div className="mt-2">导入只更新已经扫描登记的样本；如果刚修改扫描目录，请先执行扫描。</div>
          <div className="mt-1">`relative_path` 相对于数据集扫描目录；`absolute_path` 可使用 `D:/...` 或 `D:\...`，系统会归一化后匹配。除匹配字段、tags、split、notes 外，其余字段会写入样本自定义元数据。</div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">匹配字段</span>
            <select value={matchBy} onChange={(event) => setMatchBy(event.target.value)} className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none transition focus:border-gray-900">
              <option value="relative_path">relative_path</option>
              <option value="filename">filename</option>
              <option value="absolute_path">absolute_path</option>
              <option value="file_hash">file_hash</option>
              <option value="sample_id">sample_id</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">标签列</span>
            <input value={tagColumn} onChange={(event) => setTagColumn(event.target.value)} className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={replaceTags} onChange={(event) => setReplaceTags(event.target.checked)} />
          替换已有标签
        </label>
        {result && (
          <div className="rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-700">
            <div>总行数：{result.total_rows}</div>
            <div>匹配：{result.matched}</div>
            <div>更新：{result.updated}</div>
            <div>跳过：{result.skipped}</div>
            <div>错误：{result.errors.length}</div>
            {result.errors.length > 0 && (
              <div className="mt-2 max-h-28 overflow-auto rounded-md bg-white p-2 text-xs text-red-700">
                {result.errors.map((item) => (
                  <div key={item}>{item}</div>
                ))}
              </div>
            )}
          </div>
        )}
        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            关闭
          </button>
          <button type="submit" disabled={busy || !filePath.trim()} className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300">
            {busy ? "导入中" : "导入"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function apiErrorMessage(caught: unknown): string {
  if (axios.isAxiosError(caught)) {
    const detail = caught.response?.data?.detail;
    if (typeof detail === "string") {
      return detail;
    }
  }
  return "导入失败，请检查文件路径、格式和匹配字段。";
}
