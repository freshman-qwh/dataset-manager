import { FormEvent, useEffect, useState } from "react";

import type { MissingSampleRepairResult } from "../types/dataset";
import DirectoryPickerModal from "./DirectoryPickerModal";
import Modal from "./Modal";

interface MissingRepairModalProps {
  open: boolean;
  defaultPath: string;
  repairing: boolean;
  result: MissingSampleRepairResult | null;
  onClose: () => void;
  onRepair: (path: string, updateDatasetRoot: boolean) => Promise<void>;
}

export default function MissingRepairModal({
  open,
  defaultPath,
  repairing,
  result,
  onClose,
  onRepair
}: MissingRepairModalProps) {
  const [path, setPath] = useState(defaultPath);
  const [updateDatasetRoot, setUpdateDatasetRoot] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (open) {
      setPath(defaultPath);
      setUpdateDatasetRoot(true);
    }
  }, [defaultPath, open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!path.trim()) {
      return;
    }
    await onRepair(path.trim(), updateDatasetRoot);
  }

  return (
    <Modal open={open} title="修复缺失文件" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
        <div className="rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-600">
          按样本的相对路径在新目录下查找文件，找到后只更新数据库路径、hash 和文件状态，不移动或删除本地文件。
        </div>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">新的数据根目录</span>
          <div className="mt-2 flex gap-2">
            <input
              value={path}
              onChange={(event) => setPath(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder="D:/datasets/remounted"
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
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={updateDatasetRoot}
            onChange={(event) => setUpdateDatasetRoot(event.target.checked)}
          />
          同步更新数据集扫描目录
        </label>
        {result && (
          <div className="rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-700">
            <div>检查：{result.checked}</div>
            <div>修复：{result.repaired}</div>
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
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            关闭
          </button>
          <button
            type="submit"
            disabled={repairing || !path.trim()}
            className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {repairing ? "修复中" : "开始修复"}
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
