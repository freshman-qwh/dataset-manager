import { FormEvent, useEffect, useState } from "react";
import axios from "axios";

import { createTag, deleteTag, listTags, updateTag } from "../api/client";
import type { Tag } from "../types/dataset";
import { tagChipStyle } from "../utils/colors";
import Modal from "./Modal";

interface TagManagerModalProps {
  datasetId: number;
  open: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

function splitAliases(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function TagManagerModal({ datasetId, open, onClose, onChanged }: TagManagerModalProps) {
  const [tags, setTags] = useState<Tag[]>([]);
  const [editing, setEditing] = useState<Tag | null>(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState("#e5e7eb");
  const [description, setDescription] = useState("");
  const [parentId, setParentId] = useState("");
  const [aliases, setAliases] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadTags() {
    setTags(await listTags(datasetId));
  }

  useEffect(() => {
    if (open) {
      void loadTags();
      resetForm();
    }
  }, [open, datasetId]);

  function resetForm() {
    setEditing(null);
    setName("");
    setColor("#e5e7eb");
    setDescription("");
    setParentId("");
    setAliases("");
    setError(null);
  }

  function startEdit(tag: Tag) {
    setEditing(tag);
    setName(tag.name);
    setColor(tag.color || "#e5e7eb");
    setDescription(tag.description || "");
    setParentId(tag.parent_id ? String(tag.parent_id) : "");
    setAliases(tag.aliases.join(", "));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        color,
        description: description.trim() || null,
        parent_id: parentId ? Number(parentId) : null,
        aliases: splitAliases(aliases)
      };
      if (editing) {
        await updateTag(editing.id, payload);
      } else {
        await createTag(datasetId, payload);
      }
      await loadTags();
      await onChanged();
      resetForm();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(tag: Tag) {
    setBusy(true);
    setError(null);
    try {
      await deleteTag(tag.id);
      await loadTags();
      await onChanged();
      if (editing?.id === tag.id) {
        resetForm();
      }
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title="标签体系" onClose={onClose}>
      <div className="grid max-h-[78vh] gap-4 overflow-y-auto px-5 py-5 lg:grid-cols-[1fr_280px]">
        <div className="space-y-2">
          {tags.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-gray-500">
              暂无标签
            </div>
          ) : (
            tags.map((tag) => (
              <div key={tag.id} className="rounded-lg border border-line p-3">
                <div className="flex items-start justify-between gap-3">
                  <button type="button" onClick={() => startEdit(tag)} className="min-w-0 text-left">
                    <div className="flex items-center gap-2">
                      <span className="rounded-md border border-line px-2 py-0.5 text-xs font-medium" style={tagChipStyle(tag.color)}>
                        {tag.name}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-gray-500">{tag.description || "未填写描述"}</div>
                    {tag.aliases.length > 0 && <div className="mt-1 text-xs text-gray-500">别名：{tag.aliases.join(", ")}</div>}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void handleDelete(tag)}
                    className="rounded-lg border border-red-200 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-red-200"
                  >
                    删除
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-line p-3">
          <div className="text-sm font-semibold text-ink">{editing ? "编辑标签" : "新建标签"}</div>
          {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
          <label className="block">
            <span className="text-sm text-gray-700">名称 *</span>
            <input value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-gray-900" />
          </label>
          <label className="block">
            <span className="text-sm text-gray-700">颜色</span>
            <input type="color" value={color} onChange={(event) => setColor(event.target.value)} className="mt-1 h-10 w-full rounded-lg border border-line bg-white px-2 py-1" />
          </label>
          <label className="block">
            <span className="text-sm text-gray-700">父级</span>
            <select value={parentId} onChange={(event) => setParentId(event.target.value)} className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:border-gray-900">
              <option value="">无父级</option>
              {tags
                .filter((tag) => tag.id !== editing?.id)
                .map((tag) => (
                  <option key={tag.id} value={tag.id}>
                    {tag.name}
                  </option>
                ))}
            </select>
          </label>
          <label className="block">
            <span className="text-sm text-gray-700">描述</span>
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} className="mt-1 min-h-20 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-gray-900" />
          </label>
          <label className="block">
            <span className="text-sm text-gray-700">别名</span>
            <input value={aliases} onChange={(event) => setAliases(event.target.value)} className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-gray-900" placeholder="逗号分隔" />
            <span className="mt-1 block text-xs text-gray-500">名称和别名在同一数据集中不能重复，也不能互相冲突。</span>
          </label>
          <div className="flex gap-2">
            <button type="button" onClick={resetForm} className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              清空
            </button>
            <button type="submit" disabled={busy || !name.trim()} className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300">
              {busy ? "保存中" : "保存"}
            </button>
          </div>
        </form>
      </div>
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
  return "保存失败，请检查标签名称和别名是否重复。";
}
