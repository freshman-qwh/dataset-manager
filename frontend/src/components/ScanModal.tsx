import { FormEvent, useEffect, useState } from "react";

import DirectoryPickerModal from "./DirectoryPickerModal";
import Modal from "./Modal";

interface ScanModalProps {
  open: boolean;
  defaultPath: string;
  scanning: boolean;
  onClose: () => void;
  onScan: (path: string) => Promise<void>;
}

export default function ScanModal({ open, defaultPath, scanning, onClose, onScan }: ScanModalProps) {
  const [path, setPath] = useState(defaultPath);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    setPath(defaultPath);
  }, [defaultPath, open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!path.trim()) {
      return;
    }
    await onScan(path.trim());
  }

  return (
    <Modal open={open} title="扫描文件夹" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">本地目录</span>
          <div className="mt-2 flex gap-2">
            <input
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
            disabled={scanning || !path.trim()}
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
