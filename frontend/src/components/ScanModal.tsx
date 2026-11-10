import { FormEvent, useEffect, useState } from "react";

import DirectoryPickerModal from "./DirectoryPickerModal";
import Modal from "./Modal";
import ScanImportFields from "./ScanImportFields";
import type { ScanOptions } from "../types/organization";

interface ScanModalProps {
  open: boolean;
  datasetId?: number;
  defaultPath: string;
  scanning: boolean;
  receptionEnabled?: boolean;
  onClose: () => void;
  onScan: (path: string, options?: ScanOptions) => Promise<void>;
}

export default function ScanModal({ open, datasetId, defaultPath, scanning, receptionEnabled = false, onClose, onScan }: ScanModalProps) {
  const [path, setPath] = useState(defaultPath);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [options, setOptions] = useState<ScanOptions>({ import_format: "auto" });
  const [optionsValid, setOptionsValid] = useState(true);

  useEffect(() => {
    setPath(defaultPath);
    setOptions({ import_format: "auto" });
    setOptionsValid(true);
  }, [defaultPath, open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!path.trim()) {
      return;
    }
    if (scanning || !optionsValid) return;
    await onScan(path.trim(), datasetId ? options : undefined);
  }

  return (
    <Modal open={open} title="导入本地图片" onClose={onClose} dismissible={!scanning}>
      <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">本地目录</span>
          <div className="mt-2 flex gap-2">
            <input
              aria-label="导入目录"
              value={path}
              onChange={(event) => setPath(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder="D:/My Code/dataset-manager/storage/datasets/example"
            />
            <button
              type="button"
              onClick={() => setPickerOpen(true)}
              className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              选择
            </button>
          </div>
        </label>
        {datasetId && <ScanImportFields key={`${datasetId}:${open}`} datasetId={datasetId} open={open} path={path} disabled={scanning} receptionEnabled={receptionEnabled} onChange={setOptions} onValidityChange={setOptionsValid} />}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={scanning || !path.trim() || !optionsValid}
            className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {scanning ? "扫描中" : "开始扫描"}
          </button>
        </div>
      </form>
      <DirectoryPickerModal
        open={pickerOpen}
        initialPath={path || undefined}
        onClose={() => setPickerOpen(false)}
        onSelect={setPath}
      />
    </Modal>
  );
}
