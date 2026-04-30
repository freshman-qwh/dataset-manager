import { FormEvent, useEffect, useState } from "react";

import type { Dataset, DatasetCreate } from "../types/dataset";
import DirectoryPickerModal from "./DirectoryPickerModal";
import Modal from "./Modal";

interface DatasetSettingsModalProps {
  dataset: Dataset | null;
  open: boolean;
  saving: boolean;
  deleting: boolean;
  onClose: () => void;
  onSave: (payload: Partial<DatasetCreate>) => Promise<void>;
  onDelete: () => Promise<void>;
}

export default function DatasetSettingsModal({
  dataset,
  open,
  saving,
  deleting,
  onClose,
  onSave,
  onDelete
}: DatasetSettingsModalProps) {
  const [name, setName] = useState("");
  const [taskType, setTaskType] = useState("classification");
  const [rootPath, setRootPath] = useState("");
  const [project, setProject] = useState("");
  const [owner, setOwner] = useState("");
  const [source, setSource] = useState("");
  const [modality, setModality] = useState("");
  const [license, setLicense] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmName, setConfirmName] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (!dataset) {
      return;
    }
    setName(dataset.name);
    setTaskType(dataset.task_type || "classification");
    setRootPath(dataset.root_path || "");
    setProject(dataset.project || "");
    setOwner(dataset.owner || "");
    setSource(dataset.source || "");
    setModality(dataset.modality || "");
    setLicense(dataset.license || "");
    setDescription(dataset.description || "");
    setNotes(dataset.notes || "");
    setConfirmName("");
  }, [dataset, open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    await onSave({
      name: name.trim(),
      task_type: taskType.trim() || null,
      root_path: rootPath.trim() || null,
      project: project.trim() || null,
      owner: owner.trim() || null,
      source: source.trim() || null,
      modality: modality.trim() || null,
      license: license.trim() || null,
      description: description.trim() || null,
      notes: notes.trim() || null
    });
  }

  return (
    <Modal open={open} title="数据集设置" onClose={onClose}>
      <form onSubmit={handleSubmit} className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">名称 *</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">扫描目录</span>
          <div className="mt-2 flex gap-2">
            <input
              value={rootPath}
              onChange={(event) => setRootPath(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
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

        <div className="grid gap-3 sm:grid-cols-2">
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
            <span className="text-sm font-medium text-gray-700">项目</span>
            <input value={project} onChange={(event) => setProject(event.target.value)} className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">负责人</span>
            <input value={owner} onChange={(event) => setOwner(event.target.value)} className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">来源</span>
            <input value={source} onChange={(event) => setSource(event.target.value)} className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">模态</span>
            <input value={modality} onChange={(event) => setModality(event.target.value)} className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">许可</span>
            <input value={license} onChange={(event) => setLicense(event.target.value)} className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
          </label>
        </div>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">描述</span>
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} className="mt-2 min-h-24 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">备注</span>
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} className="mt-2 min-h-24 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900" />
        </label>

        <div className="rounded-lg border border-red-200 bg-red-50 p-3">
          <div className="text-sm font-medium text-red-800">删除数据集元数据</div>
          <p className="mt-1 text-sm text-red-700">只删除数据库中的数据集、样本和标签记录，不删除本地原始文件。</p>
          <input
            value={confirmName}
            onChange={(event) => setConfirmName(event.target.value)}
            className="mt-3 w-full rounded-lg border border-red-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-red-700"
            placeholder={`输入 ${dataset?.name || "数据集名称"} 确认删除`}
          />
          <button
            type="button"
            disabled={deleting || confirmName !== dataset?.name}
            onClick={onDelete}
            className="mt-3 rounded-lg bg-red-700 px-3 py-2 text-sm font-medium text-white hover:bg-red-800 disabled:cursor-not-allowed disabled:bg-red-200"
          >
            {deleting ? "删除中" : "删除元数据"}
          </button>
        </div>

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            取消
          </button>
          <button type="submit" disabled={saving || !name.trim()} className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300">
            {saving ? "保存中" : "保存"}
          </button>
        </div>
      </form>
      <DirectoryPickerModal
        open={pickerOpen}
        initialPath={rootPath || undefined}
        onClose={() => setPickerOpen(false)}
        onSelect={setRootPath}
      />
    </Modal>
  );
}
