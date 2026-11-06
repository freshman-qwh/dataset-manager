import { FormEvent, useEffect, useState } from "react";

import type { Dataset, DatasetCreate } from "../types/dataset";
import DirectoryPickerModal from "./DirectoryPickerModal";
import Modal from "./Modal";
import ProjectField from "./ProjectField";
import { organizationError, resolveProjectChoice } from "../api/organization";
import { datasetTaskOptions } from "../utils/workflow";

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
  const [profile, setProfile] = useState<"general" | "industrial_anomaly">("general");
  const [confirmProfile, setConfirmProfile] = useState(false);
  const [taskType, setTaskType] = useState<DatasetCreate["task_type"]>("detection");
  const [rootPath, setRootPath] = useState("");
  const [projectChoice, setProjectChoice] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [projectSaving, setProjectSaving] = useState(false);
  const [error, setError] = useState("");
  const [owner, setOwner] = useState("");
  const [source, setSource] = useState("");
  const [modality, setModality] = useState("");
  const [license, setLicense] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");
  const [autoScanOnOpen, setAutoScanOnOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (!dataset) {
      return;
    }
    setName(dataset.name);
    setProfile(dataset.workflow_profile ?? "general");
    setConfirmProfile(false);
    setTaskType(datasetTaskOptions.some((option) => option.value === dataset.task_type) ? dataset.task_type as DatasetCreate["task_type"] : "detection");
    setRootPath(dataset.root_path || "");
    setProjectChoice(dataset.project_id ? String(dataset.project_id) : dataset.project ? "new" : "");
    setNewProjectName(dataset.project ?? "");
    setError("");
    setOwner(dataset.owner || "");
    setSource(dataset.source || "");
    setModality(dataset.modality || "");
    setLicense(dataset.license || "");
    setDescription(dataset.description || "");
    setNotes(dataset.notes || "");
    setAutoScanOnOpen(dataset.auto_scan_on_open);
    setConfirmName("");
  }, [dataset, open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    if (profile !== dataset?.workflow_profile && !confirmProfile) return;
    if (saving || projectSaving) return;
    setProjectSaving(true); setError("");
    try {
    const projectId = await resolveProjectChoice(projectChoice, newProjectName);
    await onSave({
      name: name.trim(),
      workflow_profile: profile,
      task_type: taskType,
      root_path: rootPath.trim() || null,
      project_id: projectId,
      owner: owner.trim() || null,
      source: source.trim() || null,
      modality: modality.trim() || null,
      license: license.trim() || null,
      description: description.trim() || null,
      notes: notes.trim() || null,
      auto_scan_on_open: autoScanOnOpen
    });
    } catch (caught) { setError(organizationError(caught, "保存失败，请检查填写内容后重试。")); }
    finally { setProjectSaving(false); }
  }

  return (
    <Modal open={open} title="数据集设置" onClose={onClose} dismissible={!saving && !projectSaving}>
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
          <label className="block text-sm font-medium text-gray-700">准备用途
            <select aria-label="准备用途" value={profile} onChange={e => { setProfile(e.target.value as typeof profile); setConfirmProfile(false); }} className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5">
              <option value="general">通用数据整理</option><option value="industrial_anomaly">工业异常检测</option>
            </select>
          </label>
          {profile !== dataset?.workflow_profile && <label className="flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
            <input type="checkbox" checked={confirmProfile} onChange={e => setConfirmProfile(e.target.checked)} required />
            我确认切换用途。已有判定、标签、几何标注和划分均保留；统一 OK 仍需复核等级，不会自动变为完全正常。
          </label>}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">任务类型</span>
            <select
              value={taskType}
              onChange={(event) => setTaskType(event.target.value as DatasetCreate["task_type"])}
              className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
            >
              {datasetTaskOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            {dataset && !dataset.task_capabilities.supported && <span className="mt-1 block text-xs text-amber-700">{dataset.task_capabilities.unsupported_reason}</span>}
          </label>
          <ProjectField open={open} choice={projectChoice} newName={newProjectName} onChange={(choice, value) => {setProjectChoice(choice); setNewProjectName(value);}} />
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

        <div className="rounded-lg border border-line bg-gray-50 p-3">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={autoScanOnOpen}
              onChange={(event) => setAutoScanOnOpen(event.target.checked)}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-medium text-gray-800">打开数据集时自动扫描</span>
              <span className="mt-1 block text-xs text-gray-500">
                进入详情页后用当前扫描目录做一次增量扫描，用于及时标记缺失或变更文件。大目录会增加打开耗时。
              </span>
            </span>
          </label>
        </div>

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

        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <button type="button" disabled={saving || projectSaving} onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">
            取消
          </button>
          <button type="submit" disabled={saving || projectSaving || !name.trim()} className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300">
            {saving || projectSaving ? "保存中" : "保存"}
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
