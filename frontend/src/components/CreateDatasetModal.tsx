import { FormEvent, useState } from "react";

import type { DatasetCreate } from "../types/dataset";
import Modal from "./Modal";

interface CreateDatasetModalProps {
  open: boolean;
  onClose: () => void;
  onCreate: (payload: DatasetCreate) => Promise<void>;
}

export default function CreateDatasetModal({ open, onClose, onCreate }: CreateDatasetModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [taskType, setTaskType] = useState("classification");
  const [rootPath, setRootPath] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    setSaving(true);
    try {
      await onCreate({
        name: name.trim(),
        description: description.trim() || null,
        task_type: taskType.trim() || null,
        root_path: rootPath.trim() || null
      });
      setName("");
      setDescription("");
      setRootPath("");
      setTaskType("classification");
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="创建数据集" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">名称</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            placeholder="例如 Cell Microscopy 2026"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">任务类型</span>
          <select
            value={taskType}
            onChange={(event) => setTaskType(event.target.value)}
            className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
          >
            <option value="classification">分类</option>
            <option value="detection">检测</option>
            <option value="segmentation">分割</option>
            <option value="tabular">表格</option>
            <option value="other">其他</option>
          </select>
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">扫描目录</span>
          <input
            value={rootPath}
            onChange={(event) => setRootPath(event.target.value)}
            className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            placeholder="D:/My Code/dataset-manager/storage/datasets/example"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">描述</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="mt-2 min-h-24 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            placeholder="数据来源、用途、采集条件"
          />
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
            disabled={saving || !name.trim()}
            className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {saving ? "创建中" : "创建"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
