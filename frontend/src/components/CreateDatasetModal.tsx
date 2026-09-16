import { FormEvent, useState } from "react";

import type { DatasetCreate } from "../types/dataset";
import DirectoryPickerModal from "./DirectoryPickerModal";
import Modal from "./Modal";
import { datasetTaskOptions } from "../utils/workflow";

interface CreateDatasetModalProps {
  open: boolean;
  onClose: () => void;
  onCreate: (payload: DatasetCreate) => Promise<void>;
}

export default function CreateDatasetModal({ open, onClose, onCreate }: CreateDatasetModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [taskType, setTaskType] = useState<DatasetCreate["task_type"]>("detection");
  const [rootPath, setRootPath] = useState("");
  const [source, setSource] = useState("");
  const [modality, setModality] = useState("");
  const [license, setLicense] = useState("");
  const [owner, setOwner] = useState("");
  const [project, setProject] = useState("");
  const [saving, setSaving] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

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
        task_type: taskType,
        root_path: rootPath.trim() || null,
        source: source.trim() || null,
        modality: modality.trim() || null,
        license: license.trim() || null,
        owner: owner.trim() || null,
        project: project.trim() || null
      });
      setName("");
      setDescription("");
      setRootPath("");
      setSource("");
      setModality("");
      setLicense("");
      setOwner("");
      setProject("");
      setTaskType("detection");
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="创建数据集" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">名称 *</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            placeholder="例如 Cell Microscopy 2026"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">任务类型</span>
          <select
            value={taskType}
            onChange={(event) => setTaskType(event.target.value as DatasetCreate["task_type"])}
            className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
          >
            {datasetTaskOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <span className="mt-1 block text-xs text-gray-500">{datasetTaskOptions.find((option) => option.value === taskType)?.description}</span>
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">扫描目录</span>
          <div className="mt-2 flex gap-2">
            <input
              value={rootPath}
              onChange={(event) => setRootPath(event.target.value)}
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
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">项目</span>
            <input
              value={project}
              onChange={(event) => setProject(event.target.value)}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder="课题或项目名"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">负责人</span>
            <input
              value={owner}
              onChange={(event) => setOwner(event.target.value)}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder="团队或姓名"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">来源</span>
            <input
              value={source}
              onChange={(event) => setSource(event.target.value)}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder="仪器、公开数据或实验批次"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">模态</span>
            <input
              value={modality}
              onChange={(event) => setModality(event.target.value)}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder="image / video / csv"
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="text-sm font-medium text-gray-700">许可</span>
            <input
              value={license}
              onChange={(event) => setLicense(event.target.value)}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder="internal / CC-BY / custom"
            />
          </label>
        </div>
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
      <DirectoryPickerModal
        open={pickerOpen}
        initialPath={rootPath || undefined}
        onClose={() => setPickerOpen(false)}
        onSelect={setRootPath}
      />
    </Modal>
  );
}
