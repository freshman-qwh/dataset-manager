import { useEffect, useState } from "react";

import { getSampleFileUrl, getSampleThumbnailUrl, listSamples } from "../api/client";
import type { Sample, SampleListResponse } from "../types/dataset";
import Modal from "./Modal";

interface Props {
  datasetId: number;
  open: boolean;
  onClose: () => void;
  onSelect: (sample: Sample) => void;
}

export default function ImportSamplePickerModal({ datasetId, open, onClose, onSelect }: Props) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<SampleListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (open) { setSearch(""); setPage(1); setResult(null); }
  }, [open, datasetId]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setResult(null);
    const timer = window.setTimeout(() => {
      void listSamples({ datasetId, search, fileType: "image", page, pageSize: 12, sortBy: "relative_path", sortOrder: "asc" }, controller.signal)
        .then((data) => { if (!controller.signal.aborted) setResult(data); })
        .catch(() => { if (!controller.signal.aborted) setError("无法加载图片，请重试。"); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [datasetId, open, search, page, reload]);

  return (
    <Modal open={open} title="选择对应图片" onClose={onClose}>
      <div className="space-y-3 px-5 py-4">
        <p className="text-xs text-gray-500">选择这个 JSON 实际对应的图片，仅显示当前数据集内已登记的图片。</p>
        <label className="block text-sm text-gray-700">
          搜索图片
          <input autoFocus value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="文件名或相对路径" className="mt-2 w-full rounded-lg border border-line px-3 py-2 outline-none focus:border-gray-900" />
        </label>
        <div className="max-h-[45vh] overflow-y-auto rounded-lg border border-line" aria-live="polite">
          {loading ? <p className="p-5 text-center text-sm text-gray-500">加载中…</p> : error ? <div className="p-4 text-sm text-red-700">{error}<button type="button" onClick={() => setReload(reload + 1)} className="ml-2 underline">重试</button></div> : result?.items.length ? result.items.map((sample) => (
            <button key={sample.id} type="button" onClick={() => { onSelect(sample); onClose(); }} className="flex w-full items-center gap-3 border-b border-line p-3 text-left last:border-0 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-gray-900">
              <ImportSampleThumbnail sample={sample} />
              <span className="min-w-0"><span className="block truncate text-sm font-medium text-gray-800">{sample.filename}</span><span className="block break-all text-xs text-gray-500">{sample.relative_path}</span></span>
            </button>
          )) : <p className="p-5 text-center text-sm text-gray-500">{search ? "没有匹配的图片" : "暂无已登记图片，请先扫描数据集。"}</p>}
        </div>
        {result && result.total > 12 ? <div className="flex items-center justify-between text-sm text-gray-600">
          <button type="button" disabled={loading || page === 1} onClick={() => setPage(page - 1)} className="rounded border border-line px-3 py-2 disabled:opacity-40">上一页</button>
          <span>{page} / {Math.ceil(result.total / 12)}</span>
          <button type="button" disabled={loading || page * 12 >= result.total} onClick={() => setPage(page + 1)} className="rounded border border-line px-3 py-2 disabled:opacity-40">下一页</button>
        </div> : null}
        <div className="flex justify-end"><button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm text-gray-700">返回导入设置</button></div>
      </div>
    </Modal>
  );
}

export function ImportSampleThumbnail({ sample }: { sample: Sample }) {
  const [failed, setFailed] = useState(0);
  useEffect(() => setFailed(0), [sample.id, sample.file_hash]);
  if (failed > 1) return <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded bg-gray-50 text-xs text-gray-500">无预览</span>;
  return <img loading="lazy" src={failed ? getSampleFileUrl(sample.id) : getSampleThumbnailUrl(sample.id, sample.file_hash)} alt="" onError={() => setFailed(failed + 1)} className="h-12 w-16 shrink-0 rounded bg-gray-50 object-contain" />;
}
