import { ArrowLeft, Image as ImageIcon, Loader2, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  getDataset,
  getSample,
  getSampleFileUrl,
  listSampleAnnotations,
  listSamples,
  listTags,
  replaceSampleAnnotations
} from "../api/client";
import AnnotationCanvas from "../components/annotation/AnnotationCanvas";
import AnnotationObjectList from "../components/annotation/AnnotationObjectList";
import AnnotationToolbar, { type AnnotationTool } from "../components/annotation/AnnotationToolbar";
import { useAnnotationHistory } from "../components/annotation/useAnnotationHistory";
import type { AnnotationObject, AnnotationReplaceItem, Dataset, Sample, Tag } from "../types/dataset";

function normalizeObjects(objects: AnnotationObject[]): AnnotationObject[] {
  return objects.map((object, index) => ({ ...object, z_order: index }));
}

function confirmDiscard(dirty: boolean): boolean {
  return !dirty || window.confirm("当前标注尚未保存。确定放弃这些修改吗？");
}

export default function AnnotationPage() {
  const params = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const datasetId = Number(params.datasetId);
  const requestedSampleId = Number(searchParams.get("sample"));
  const history = useAnnotationHistory();
  const { objects, reset, replace, commit, undo, redo, canUndo, canRedo } = history;
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tool, setTool] = useState<AnnotationTool>("select");
  const [activeObjectId, setActiveObjectId] = useState<string | null>(null);
  const [activeLabel, setActiveLabel] = useState("object");
  const [status, setStatus] = useState("准备就绪");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeTag = useMemo(
    () => tags.find((tag) => tag.name.toLowerCase() === activeLabel.trim().toLowerCase()) ?? null,
    [activeLabel, tags]
  );
  const activeObject = useMemo(
    () => objects.find((object) => object.client_id === activeObjectId) ?? null,
    [activeObjectId, objects]
  );

  const loadWorkspace = useCallback(async () => {
    if (!Number.isFinite(datasetId)) {
      setError("数据集 ID 无效");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [nextDataset, nextTags] = await Promise.all([getDataset(datasetId), listTags(datasetId)]);
      let targetSampleId = Number.isFinite(requestedSampleId) && requestedSampleId > 0 ? requestedSampleId : null;
      if (!targetSampleId) {
        const imageSamples = await listSamples({ datasetId, fileType: "image", page: 1, pageSize: 1 });
        targetSampleId = imageSamples.items[0]?.id ?? null;
        if (targetSampleId) {
          setSearchParams({ sample: String(targetSampleId) }, { replace: true });
        }
      }
      if (!targetSampleId) {
        setDataset(nextDataset);
        setTags(nextTags);
        setSample(null);
        reset([]);
        setError("当前数据集没有可标注的图片样本");
        return;
      }
      const [nextSample, nextAnnotations] = await Promise.all([
        getSample(targetSampleId),
        listSampleAnnotations(targetSampleId)
      ]);
      setDataset(nextDataset);
      setTags(nextTags);
      setSample(nextSample);
      reset(normalizeObjects(nextAnnotations));
      setActiveObjectId(nextAnnotations[0]?.client_id ?? null);
      setActiveLabel(nextTags[0]?.name ?? nextAnnotations[0]?.label ?? "object");
      setDirty(false);
      if (nextSample.file_type !== "image") {
        setError("当前样本不是图片，暂不支持几何标注");
      }
    } catch {
      setError("标注工作区加载失败");
    } finally {
      setLoading(false);
    }
  }, [datasetId, requestedSampleId, reset, setSearchParams]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!dirty) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void handleSave();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undo();
        setDirty(true);
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        redo();
        setDirty(true);
      } else if (event.key.toLowerCase() === "v") {
        setTool("select");
      } else if (event.key.toLowerCase() === "r") {
        setTool("rectangle");
      } else if (event.key.toLowerCase() === "p") {
        setTool("polygon");
      } else if (event.key.toLowerCase() === "h") {
        setTool("pan");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  function commitObjects(nextObjects: AnnotationObject[], previousObjects = objects) {
    commit(normalizeObjects(nextObjects), normalizeObjects(previousObjects));
    setDirty(true);
  }

  function updateObject(clientId: string, updates: Partial<AnnotationObject>) {
    const previous = objects;
    const next = objects.map((object) => (object.client_id === clientId ? { ...object, ...updates } : object));
    commitObjects(next, previous);
  }

  function deleteObject(clientId: string) {
    const previous = objects;
    const next = objects.filter((object) => object.client_id !== clientId);
    commitObjects(next, previous);
    if (activeObjectId === clientId) {
      setActiveObjectId(next[0]?.client_id ?? null);
    }
  }

  function deleteActiveObject() {
    if (activeObjectId) {
      deleteObject(activeObjectId);
    }
  }

  function buildSavePayload(): AnnotationReplaceItem[] {
    return normalizeObjects(objects)
      .filter((object) => object.label.trim() && object.points.length >= 2)
      .map((object) => {
        const matchedTag = tags.find((tag) => tag.name.toLowerCase() === object.label.trim().toLowerCase());
        return {
          label: object.label.trim(),
          tag_id: matchedTag?.id ?? object.tag_id ?? null,
          shape_type: object.shape_type,
          points: object.points,
          flags: object.flags,
          attributes: object.attributes,
          group_id: object.group_id,
          z_order: object.z_order,
          locked: object.locked,
          hidden: object.hidden,
          source: object.source || "manual",
          notes: object.notes
        };
      });
  }

  async function handleSave() {
    if (!sample || saving) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await replaceSampleAnnotations(sample.id, { annotations: buildSavePayload() });
      reset(normalizeObjects(saved));
      setActiveObjectId(saved[0]?.client_id ?? null);
      setDirty(false);
      const [nextSample, nextTags] = await Promise.all([getSample(sample.id), listTags(datasetId)]);
      setSample(nextSample);
      setTags(nextTags);
      setStatus("标注已保存");
    } catch {
      setError("标注保存失败，请检查对象类别和坐标是否有效");
    } finally {
      setSaving(false);
    }
  }

  function handleBack() {
    if (confirmDiscard(dirty)) {
      navigate(`/datasets/${datasetId}`);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-canvas text-gray-600">
        <Loader2 className="mr-2 animate-spin" size={18} />
        正在加载标注工作区
      </main>
    );
  }

  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden bg-canvas">
      <header className="shrink-0 border-b border-line bg-white">
        <div className="flex flex-col gap-3 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={handleBack}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50"
              title="返回数据集"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="min-w-0">
              <div className="truncate text-sm text-gray-500">{dataset?.name ?? "数据集"}</div>
              <h1 className="truncate text-lg font-semibold text-ink">{sample?.filename ?? "未选择样本"}</h1>
            </div>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
            {sample && (
              <span className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-lg border border-line bg-gray-50 px-3 py-2 text-gray-600 lg:max-w-md">
                <ImageIcon className="shrink-0" size={16} />
                <span className="truncate">{sample.relative_path}</span>
              </span>
            )}
            <span className={`rounded-lg px-3 py-2 ${dirty ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>
              {saving ? "保存中" : dirty ? "有未保存修改" : "已保存"}
            </span>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || !dirty}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              <Save size={17} />
              保存
            </button>
          </div>
        </div>
      </header>

      {error && <div className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <section className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <AnnotationToolbar
          tool={tool}
          label={activeLabel}
          tags={tags}
          dirty={dirty}
          saving={saving}
          canUndo={canUndo}
          canRedo={canRedo}
          hasActiveObject={Boolean(activeObject)}
          onToolChange={setTool}
          onLabelChange={setActiveLabel}
          onSave={() => void handleSave()}
          onUndo={() => {
            undo();
            setDirty(true);
          }}
          onRedo={() => {
            redo();
            setDirty(true);
          }}
          onDeleteActive={deleteActiveObject}
        />
        {sample?.file_type === "image" && sample.file_status === "normal" ? (
          <AnnotationCanvas
            imageUrl={getSampleFileUrl(sample.id)}
            objects={objects}
            activeObjectId={activeObjectId}
            tool={tool}
            activeLabel={activeLabel}
            activeTagId={activeTag?.id ?? null}
            tags={tags}
            onObjectsPreview={replace}
            onObjectsCommit={commitObjects}
            onActiveObjectChange={setActiveObjectId}
            onStatusChange={setStatus}
            onDeleteActive={deleteActiveObject}
          />
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center bg-gray-100 text-sm text-gray-500">
            当前样本不可标注，请选择正常状态的图片样本。
          </div>
        )}
        <AnnotationObjectList
          objects={objects}
          activeObjectId={activeObjectId}
          tags={tags}
          onSelect={setActiveObjectId}
          onUpdate={updateObject}
          onDelete={deleteObject}
        />
      </section>

      <footer className="shrink-0 border-t border-line bg-white px-4 py-2 text-xs text-gray-500">
        {status} · 快捷键：V 选择，R 矩形，P 多边形，H 平移，Ctrl+S 保存，Delete 删除
      </footer>
    </main>
  );
}
