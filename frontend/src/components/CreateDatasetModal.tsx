import axios from "axios";
import { FormEvent, useEffect, useRef, useState } from "react";

import type { DatasetCreate } from "../types/dataset";
import DirectoryPickerModal from "./DirectoryPickerModal";
import Modal from "./Modal";
import ProjectField from "./ProjectField";
import { organizationError, resolveProjectChoice } from "../api/organization";
import { datasetTaskOptions } from "../utils/workflow";

interface CreateDatasetModalProps {
  open: boolean;
  onClose: () => void;
  onCreate: (payload: DatasetCreate) => Promise<void>;
}

export default function CreateDatasetModal({ open, onClose, onCreate }: CreateDatasetModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [taskType, setTaskType] = useState<DatasetCreate["task_type"]>("classification");
  const [profile, setProfile] = useState<"general" | "industrial_anomaly">("industrial_anomaly");
  const [rootPath, setRootPath] = useState("");
  const [source, setSource] = useState("");
  const [modality, setModality] = useState("");
  const [license, setLicense] = useState("");
  const [owner, setOwner] = useState("");
  const [projectChoice, setProjectChoice] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [saving, setSaving] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);

  useEffect(() => {
    if (open) setError("");
  }, [open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || submitting.current) {
      return;
    }
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const projectId = await resolveProjectChoice(projectChoice, newProjectName);
      await onCreate({
        name: name.trim(),
        description: description.trim() || null,
        task_type: taskType,
        workflow_profile: profile,
        root_path: rootPath.trim() || null,
        source: source.trim() || null,
        modality: modality.trim() || null,
        license: license.trim() || null,
        owner: owner.trim() || null,
        project_id: projectId
      });
      setName("");
      setDescription("");
      setRootPath("");
      setSource("");
      setModality("");
      setLicense("");
      setOwner("");
      setProjectChoice(""); setNewProjectName("");
      setTaskType(profile === "industrial_anomaly" ? "classification" : "detection");
      onClose();
    } catch (caught) {
      const detail: unknown = axios.isAxiosError(caught) ? caught.response?.data?.detail : undefined;
      setError(typeof detail === "string" ? detail : organizationError(caught, "创建失败，请检查后端服务和填写内容后重试。已填写的信息会保留。"));
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  const taskSelection = <label className="block">
    <span className="text-sm font-medium text-gray-700">{profile === "industrial_anomaly" ? "标注方式" : "任务类型"}</span>
    <select
      value={taskType}
      onChange={(event) => setTaskType(event.target.value as DatasetCreate["task_type"])}
      className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
    >
      {datasetTaskOptions.map((option) => <option key={option.value} value={option.value}>{profile === "industrial_anomaly" && option.value === "classification" ? "只做图像级判定（无需画框）" : option.label}</option>)}
    </select>
    <span className="mt-2 block text-xs leading-5 text-gray-500">{profile === "industrial_anomaly" && taskType === "classification" ? "正常、临界和异常通过分拣记录，快速验证无需绘制标注。" : datasetTaskOptions.find((option) => option.value === taskType)?.description}</span>
  </label>;

  return (
    <Modal open={open} title="创建数据集" onClose={onClose} dismissible={!saving}>
      <form onSubmit={handleSubmit} className="px-5 py-5" aria-busy={saving}>
        <fieldset disabled={saving} className="min-w-0 space-y-5">
          <p className="text-sm leading-6 text-gray-500">填写名称即可开始，图片目录和补充资料也可以稍后设置。</p>
          <label className="block text-sm font-medium text-gray-700">准备目标
            <select aria-label="准备目标" value={profile} onChange={(event) => {
              const next = event.target.value as typeof profile;
              setProfile(next); setTaskType(next === "industrial_anomaly" ? "classification" : "detection");
            }} className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5">
              <option value="industrial_anomaly">工业异常检测</option><option value="general">通用检测 / 分割 / 分类</option>
            </select>
            {profile === "industrial_anomaly" && <span className="mt-2 block text-xs font-normal leading-5 text-gray-500">分拣正常与异常，确认工件分组，再快速验证或导出训练包。</span>}
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">名称 *</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              maxLength={160}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
              placeholder={profile === "industrial_anomaly" ? "例如 齿轮表面检测 · 首批" : "例如 零件目标检测"}
            />
          </label>
          <ProjectField open={open} choice={projectChoice} newName={newProjectName} onChange={(choice, value) => {setProjectChoice(choice); setNewProjectName(value);}} />
          {profile === "general" && taskSelection}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">图片目录 <span className="font-normal text-gray-500">（可选）</span></span>
            <div className="mt-2 flex gap-2">
              <input
                value={rootPath}
                onChange={(event) => setRootPath(event.target.value)}
                className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
                placeholder="选择本机图片文件夹"
              />
              <button
                type="button"
                onClick={() => setPickerOpen(true)}
                className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                浏览
              </button>
            </div>
            <span className="mt-2 block text-xs leading-5 text-gray-500">创建后扫描此目录登记图片，不移动或修改原图；留空可稍后选择。</span>
          </label>
          {profile === "industrial_anomaly" && <details className="rounded-lg border border-line p-3">
            <summary className="cursor-pointer text-sm font-medium text-gray-700">补充几何标注（可选）</summary>
            <div className="mt-4">{taskSelection}</div>
          </details>}
          <details className="rounded-lg border border-line p-3">
            <summary className="cursor-pointer text-sm font-medium text-gray-700">补充资料（可选）</summary>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
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
              <label className="block sm:col-span-2">
                <span className="text-sm font-medium text-gray-700">描述</span>
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  className="mt-2 min-h-24 w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none transition focus:border-gray-900"
                  placeholder="数据来源、用途、采集条件"
                />
              </label>
            </div>
          </details>
          {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">{error}</p>}
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
              {saving ? "创建中…" : "创建并开始"}
            </button>
          </div>
        </fieldset>
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
