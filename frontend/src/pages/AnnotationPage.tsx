import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  Image as ImageIcon,
  Loader2,
  Save
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  getDataset,
  getSample,
  getSampleFileUrl,
  getSampleNavigation,
  listSampleAnnotations,
  listTags,
  replaceSampleAnnotations
} from "../api/client";
import AnnotationCanvas, {
  type AnnotationDraftCommand,
  type AnnotationDraftState,
  type AnnotationFocusCommand
} from "../components/annotation/AnnotationCanvas";
import AnnotationObjectList from "../components/annotation/AnnotationObjectList";
import AnnotationToolbar, { type AnnotationTool } from "../components/annotation/AnnotationToolbar";
import { useAnnotationHistory } from "../components/annotation/useAnnotationHistory";
import type {
  AnnotationObject,
  AnnotationReplaceItem,
  Dataset,
  Sample,
  SampleNavigationResponse,
  Tag
} from "../types/dataset";

const EMPTY_DRAFT_STATE: AnnotationDraftState = { active: false, shapeType: null, canCommit: false };
const AUTO_SAVE_ON_NAVIGATION_KEY = "dataset-manager.annotation.autoSaveOnNavigation";

type DeferredAction = () => void | Promise<void>;

interface PendingAction {
  title: string;
  description: string;
  action: DeferredAction;
  commitLabel?: string;
  cancelLabel?: string;
}

interface KeyboardShortcutActions {
  requestSave: () => void;
  undoAndMarkDirty: () => void;
  redoAndMarkDirty: () => void;
  changeTool: (tool: AnnotationTool) => void;
  switchPrevious: () => void;
  switchNext: () => void;
}

function normalizeObjects(objects: AnnotationObject[]): AnnotationObject[] {
  return objects.map((object, index) => ({ ...object, z_order: index }));
}

function isAnnotatableImage(sample: Sample): boolean {
  return sample.file_type === "image" && sample.file_status === "normal";
}

export default function AnnotationPage() {
  const params = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchParamsText = searchParams.toString();
  const datasetId = Number(params.datasetId);
  const requestedSampleId = Number(searchParams.get("sample"));
  const history = useAnnotationHistory();
  const { objects, reset, replace, commit, undo, redo, canUndo, canRedo } = history;
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  const [navigation, setNavigation] = useState<SampleNavigationResponse | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tool, setTool] = useState<AnnotationTool>("select");
  const [activeObjectId, setActiveObjectId] = useState<string | null>(null);
  const [activeLabel, setActiveLabel] = useState("object");
  const [status, setStatus] = useState("准备就绪");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [navigationLoading, setNavigationLoading] = useState(false);
  const [sampleLoading, setSampleLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftState, setDraftState] = useState<AnnotationDraftState>(EMPTY_DRAFT_STATE);
  const [draftCommand, setDraftCommand] = useState<AnnotationDraftCommand | null>(null);
  const [focusCommand, setFocusCommand] = useState<AnnotationFocusCommand | null>(null);
  const [pendingDraftAction, setPendingDraftAction] = useState<PendingAction | null>(null);
  const [pendingDirtyAction, setPendingDirtyAction] = useState<PendingAction | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [autoSaveOnNavigation, setAutoSaveOnNavigation] = useState(() => {
    try {
      return window.localStorage.getItem(AUTO_SAVE_ON_NAVIGATION_KEY) === "true";
    } catch {
      return false;
    }
  });
  const dirtyRef = useRef(false);
  const draftCommandIdRef = useRef(0);
  const focusCommandIdRef = useRef(0);
  const actionAfterDraftRef = useRef<DeferredAction | null>(null);
  const sampleRef = useRef<Sample | null>(null);
  const keyboardShortcutsRef = useRef<KeyboardShortcutActions | null>(null);

  const navigationQuery = useMemo(() => {
    const context = new URLSearchParams(searchParamsText);
    const contextFileStatus = context.get("fileStatus") || "";
    return {
      search: context.get("search") || undefined,
      fileStatus: contextFileStatus === "duplicate" ? "duplicate" : "normal",
      tag: context.get("tag") || undefined,
      split: context.get("split") || undefined,
      reviewStatus: context.get("reviewStatus") || undefined,
      sortBy: context.get("sortBy") || "created_at",
      sortOrder: context.get("sortOrder") === "asc" ? ("asc" as const) : ("desc" as const)
    };
  }, [searchParamsText]);

  const activeTag = useMemo(
    () => tags.find((tag) => tag.name.toLowerCase() === activeLabel.trim().toLowerCase()) ?? null,
    [activeLabel, tags]
  );
  const activeObject = useMemo(
    () => objects.find((object) => object.client_id === activeObjectId) ?? null,
    [activeObjectId, objects]
  );
  const previousSample = navigation?.previous_sample ?? null;
  const nextSample = navigation?.next_sample ?? null;
  const navigationLabel =
    !navigation || navigation.total === 0
      ? "无可导航图片"
      : navigation.current_index !== null
        ? `${navigation.current_index + 1} / ${navigation.total}`
        : "不在当前筛选结果";
  const hasUnsavedState = dirty || draftState.active;

  const setClean = useCallback(() => {
    dirtyRef.current = false;
    setDirty(false);
  }, []);

  const markDirty = useCallback(() => {
    dirtyRef.current = true;
    setDirty(true);
  }, []);

  useEffect(() => {
    sampleRef.current = sample;
  }, [sample]);

  const loadWorkspace = useCallback(async () => {
    if (!Number.isFinite(datasetId)) {
      setError("数据集 ID 无效");
      setLoading(false);
      return;
    }
    const initialLoad = !sampleRef.current;
    setLoading(initialLoad);
    setSampleLoading(!initialLoad);
    setNavigationLoading(true);
    setError(null);
    try {
      const targetSampleId = Number.isFinite(requestedSampleId) && requestedSampleId > 0 ? requestedSampleId : null;
      const [nextDataset, nextTags, nextNavigation] = await Promise.all([
        getDataset(datasetId),
        listTags(datasetId),
        getSampleNavigation({
          datasetId,
          sampleId: targetSampleId,
          search: navigationQuery.search,
          fileStatus: navigationQuery.fileStatus,
          tag: navigationQuery.tag,
          split: navigationQuery.split,
          reviewStatus: navigationQuery.reviewStatus,
          sortBy: navigationQuery.sortBy,
          sortOrder: navigationQuery.sortOrder
        })
      ]);
      const nextNavigationSample = nextNavigation.current_sample;
      if (!targetSampleId && nextNavigationSample) {
        const nextParams = new URLSearchParams(searchParamsText);
        nextParams.set("sample", String(nextNavigationSample.id));
        setSearchParams(nextParams, { replace: true });
      }
      setNavigation(nextNavigation);
      if (!nextNavigationSample) {
        setDataset(nextDataset);
        setTags(nextTags);
        setSample(null);
        reset([]);
        setClean();
        setDraftState(EMPTY_DRAFT_STATE);
        setError("当前筛选条件下没有可标注的正常图片样本");
        return;
      }
      const [nextSample, nextAnnotations] = await Promise.all([
        getSample(nextNavigationSample.id),
        listSampleAnnotations(nextNavigationSample.id)
      ]);
      setDataset(nextDataset);
      setTags(nextTags);
      setSample(nextSample);
      reset(normalizeObjects(nextAnnotations));
      setActiveObjectId(nextAnnotations[0]?.client_id ?? null);
      setActiveLabel(nextTags[0]?.name ?? nextAnnotations[0]?.label ?? "object");
      setClean();
      setDraftState(EMPTY_DRAFT_STATE);
      setDraftCommand(null);
      setFocusCommand(null);
      setPendingDraftAction(null);
      setPendingDirtyAction(null);
      if (!isAnnotatableImage(nextSample)) {
        setError("当前样本不是正常状态的图片，暂不支持几何标注");
      }
    } catch {
      setError("标注工作区加载失败");
    } finally {
      setLoading(false);
      setSampleLoading(false);
      setNavigationLoading(false);
    }
  }, [datasetId, navigationQuery, requestedSampleId, reset, searchParamsText, setClean, setSearchParams]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    try {
      window.localStorage.setItem(AUTO_SAVE_ON_NAVIGATION_KEY, String(autoSaveOnNavigation));
    } catch {
      // Ignore storage failures; the toggle still works for the current session.
    }
  }, [autoSaveOnNavigation]);

  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!dirtyRef.current && !draftState.active) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [draftState.active]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
        return;
      }
      const actions = keyboardShortcutsRef.current;
      if (!actions) {
        return;
      }
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === "s") {
        event.preventDefault();
        actions.requestSave();
      } else if ((event.ctrlKey || event.metaKey) && key === "z") {
        event.preventDefault();
        actions.undoAndMarkDirty();
      } else if ((event.ctrlKey || event.metaKey) && key === "y") {
        event.preventDefault();
        actions.redoAndMarkDirty();
      } else if (key === "v") {
        actions.changeTool("select");
      } else if (key === "r") {
        actions.changeTool("rectangle");
      } else if (key === "p") {
        actions.changeTool("polygon");
      } else if (key === "h") {
        actions.changeTool("pan");
      } else if (event.key === "[") {
        event.preventDefault();
        actions.switchPrevious();
      } else if (event.key === "]") {
        event.preventDefault();
        actions.switchNext();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  function commitObjects(nextObjects: AnnotationObject[], previousObjects = objects) {
    commit(normalizeObjects(nextObjects), normalizeObjects(previousObjects));
    markDirty();
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

  async function handleSave(): Promise<boolean> {
    if (!sample || saving) {
      return false;
    }
    if (!dirtyRef.current) {
      setStatus("没有需要保存的修改");
      return true;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await replaceSampleAnnotations(sample.id, { annotations: buildSavePayload(), sync_sample_tags: true });
      reset(normalizeObjects(saved));
      setActiveObjectId(saved[0]?.client_id ?? null);
      setClean();
      const [nextSample, nextTags] = await Promise.all([getSample(sample.id), listTags(datasetId)]);
      setSample(nextSample);
      setTags(nextTags);
      setStatus("标注已保存");
      return true;
    } catch {
      setError("标注保存失败，请检查对象类别和坐标是否有效");
      return false;
    } finally {
      setSaving(false);
    }
  }

  function requestDirtyAction(action: DeferredAction, title: string, description: string) {
    if (dirtyRef.current) {
      setPendingDirtyAction({ title, description, action });
      return;
    }
    void action();
  }

  function requestDraftAction(action: DeferredAction, title: string, description: string, labels?: Pick<PendingAction, "commitLabel" | "cancelLabel">) {
    if (!draftState.active) {
      void action();
      return;
    }
    setPendingDraftAction({ title, description, action, ...labels });
  }

  function requestSampleNavigationAction(action: DeferredAction) {
    const guardedAction = async () => {
      if (autoSaveOnNavigation && dirtyRef.current) {
        const saved = await handleSave();
        if (saved) {
          await action();
        }
        return;
      }
      requestDirtyAction(action, "处理未保存修改", "切换样本前，请选择保存当前标注、放弃修改或取消切换。");
    };
    requestDraftAction(
      guardedAction,
      "处理绘制中的对象",
      "切换样本前，需要先提交或取消当前正在绘制的对象。",
      { commitLabel: "提交草稿并继续", cancelLabel: "取消草稿并继续" }
    );
  }

  function requestNavigationAction(action: DeferredAction, description: string) {
    const guardedAction = () =>
      requestDirtyAction(action, "处理未保存修改", description);
    requestDraftAction(
      guardedAction,
      "处理绘制中的对象",
      "切换页面或样本前，需要先提交或取消当前正在绘制的对象。",
      { commitLabel: "提交草稿并继续", cancelLabel: "取消草稿并继续" }
    );
  }

  function requestSave() {
    requestDraftAction(
      () => void handleSave(),
      "处理绘制中的对象",
      "保存前需要先提交或取消当前正在绘制的对象。",
      { commitLabel: "提交草稿并保存", cancelLabel: "取消草稿并保存" }
    );
  }

  function handleToolChange(nextTool: AnnotationTool) {
    if (tool === nextTool) {
      return;
    }
    requestDraftAction(
      () => setTool(nextTool),
      "处理绘制中的对象",
      "切换工具前，需要先提交或取消当前正在绘制的对象。",
      { commitLabel: "提交草稿并切换", cancelLabel: "取消草稿并切换" }
    );
  }

  function runDraftCommand(action: AnnotationDraftCommand["action"]) {
    const pending = pendingDraftAction;
    if (!pending) {
      return;
    }
    actionAfterDraftRef.current = pending.action;
    setPendingDraftAction(null);
    const nextCommand = { id: draftCommandIdRef.current + 1, action };
    draftCommandIdRef.current = nextCommand.id;
    setDraftCommand(nextCommand);
  }

  function handleDraftCommandHandled(commandId: number) {
    setDraftCommand((current) => (current?.id === commandId ? null : current));
    const nextAction = actionAfterDraftRef.current;
    actionAfterDraftRef.current = null;
    if (nextAction) {
      window.setTimeout(() => {
        void nextAction();
      }, 0);
    }
  }

  async function handlePendingDirtySave() {
    const pending = pendingDirtyAction;
    if (!pending) {
      return;
    }
    const saved = await handleSave();
    if (!saved) {
      return;
    }
    setPendingDirtyAction(null);
    await pending.action();
  }

  function handlePendingDirtyDiscard() {
    const pending = pendingDirtyAction;
    if (!pending) {
      return;
    }
    setPendingDirtyAction(null);
    setClean();
    void pending.action();
  }

  function handleBack() {
    requestNavigationAction(
      () => navigate(`/datasets/${datasetId}`),
      "返回数据集前，请选择保存当前标注、放弃修改或取消返回。"
    );
  }

  function setSampleInUrl(sampleId: number) {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("sample", String(sampleId));
    setSearchParams(nextParams);
  }

  function switchSample(target: Sample | null) {
    if (!target || target.id === sample?.id) {
      return;
    }
    requestSampleNavigationAction(() => setSampleInUrl(target.id));
  }

  function handleObjectSelect(clientId: string) {
    setActiveObjectId(clientId);
    const nextCommand = { id: focusCommandIdRef.current + 1, clientId };
    focusCommandIdRef.current = nextCommand.id;
    setFocusCommand(nextCommand);
  }

  function handleFocusCommandHandled(commandId: number) {
    setFocusCommand((current) => (current?.id === commandId ? null : current));
  }

  keyboardShortcutsRef.current = {
    requestSave,
    undoAndMarkDirty: () => {
      undo();
      markDirty();
    },
    redoAndMarkDirty: () => {
      redo();
      markDirty();
    },
    changeTool: handleToolChange,
    switchPrevious: () => switchSample(previousSample),
    switchNext: () => switchSample(nextSample)
  };

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
            <div className="flex items-center gap-1">
              <button
                type="button"
                title="上一张图片"
                disabled={!previousSample || navigationLoading}
                onClick={() => switchSample(previousSample)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
              >
                <ChevronLeft size={18} />
              </button>
              <button
                type="button"
                title="下一张图片"
                disabled={!nextSample || navigationLoading}
                onClick={() => switchSample(nextSample)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
              >
                <ChevronRight size={18} />
              </button>
            </div>
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2 text-sm text-gray-500">
                <span className="truncate">{dataset?.name ?? "数据集"}</span>
                <span className="shrink-0 rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                  {navigationLoading ? "加载顺序" : navigationLabel}
                </span>
              </div>
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
            <span
              className={`min-w-24 rounded-lg px-3 py-2 text-center ${
                hasUnsavedState ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"
              }`}
            >
              {saving ? "保存中" : sampleLoading ? "加载中" : draftState.active ? "有未提交草稿" : dirty ? "有未保存修改" : "已保存"}
            </span>
            <label className="inline-flex h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-gray-700">
              <input
                type="checkbox"
                checked={autoSaveOnNavigation}
                onChange={(event) => setAutoSaveOnNavigation(event.target.checked)}
                className="h-4 w-4 rounded border-line text-gray-900"
              />
              <span>切换自动保存</span>
            </label>
            <div className="relative">
              <button
                type="button"
                title="快捷键"
                onClick={() => setHelpOpen((value) => !value)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50"
              >
                <HelpCircle size={18} />
              </button>
              {helpOpen && (
                <div className="absolute right-0 top-12 z-30 w-64 rounded-lg border border-line bg-white p-3 text-xs text-gray-600 shadow-lg">
                  <div className="mb-2 text-sm font-semibold text-ink">快捷键</div>
                  <div className="grid grid-cols-[72px_1fr] gap-x-3 gap-y-1">
                    <span className="font-medium text-gray-900">V</span>
                    <span>选择</span>
                    <span className="font-medium text-gray-900">R</span>
                    <span>矩形</span>
                    <span className="font-medium text-gray-900">P</span>
                    <span>多边形</span>
                    <span className="font-medium text-gray-900">H</span>
                    <span>平移</span>
                    <span className="font-medium text-gray-900">[ / ]</span>
                    <span>上一张 / 下一张</span>
                    <span className="font-medium text-gray-900">Ctrl+S</span>
                    <span>保存</span>
                    <span className="font-medium text-gray-900">Delete</span>
                    <span>删除当前对象</span>
                    <span className="font-medium text-gray-900">Esc</span>
                    <span>取消绘制中草稿</span>
                  </div>
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={requestSave}
              disabled={saving || (!dirty && !draftState.active)}
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
          dirty={dirty || draftState.active}
          saving={saving}
          canUndo={canUndo}
          canRedo={canRedo}
          hasActiveObject={Boolean(activeObject)}
          onToolChange={handleToolChange}
          onLabelChange={setActiveLabel}
          onSave={requestSave}
          onUndo={() => {
            undo();
            markDirty();
          }}
          onRedo={() => {
            redo();
            markDirty();
          }}
          onDeleteActive={deleteActiveObject}
        />
        {sample && isAnnotatableImage(sample) ? (
          <AnnotationCanvas
            imageUrl={getSampleFileUrl(sample.id)}
            objects={objects}
            activeObjectId={activeObjectId}
            tool={tool}
            activeLabel={activeLabel}
            activeTagId={activeTag?.id ?? null}
            tags={tags}
            draftCommand={draftCommand}
            focusCommand={focusCommand}
            onObjectsPreview={replace}
            onObjectsCommit={commitObjects}
            onActiveObjectChange={setActiveObjectId}
            onStatusChange={setStatus}
            onDeleteActive={deleteActiveObject}
            onDraftStateChange={setDraftState}
            onDraftCommandHandled={handleDraftCommandHandled}
            onFocusCommandHandled={handleFocusCommandHandled}
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
          onSelect={handleObjectSelect}
          onUpdate={updateObject}
          onDelete={deleteObject}
        />
      </section>

      <footer className="shrink-0 border-t border-line bg-white px-4 py-2 text-xs text-gray-500">
        {status} · 快捷键在右上角帮助中查看
      </footer>

      {pendingDraftAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-md rounded-lg border border-line bg-white p-5 shadow-xl">
            <h2 className="text-base font-semibold text-ink">{pendingDraftAction.title}</h2>
            <p className="mt-2 text-sm text-gray-600">{pendingDraftAction.description}</p>
            {!draftState.canCommit && (
              <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                当前草稿还不满足提交条件，只能取消草稿或返回继续绘制。
              </p>
            )}
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => {
                  setPendingDraftAction(null);
                  actionAfterDraftRef.current = null;
                }}
                className="inline-flex h-10 items-center justify-center rounded-lg border border-line px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                返回编辑
              </button>
              <button
                type="button"
                onClick={() => runDraftCommand("cancel")}
                className="inline-flex h-10 items-center justify-center rounded-lg border border-amber-200 px-4 text-sm font-medium text-amber-700 hover:bg-amber-50"
              >
                {pendingDraftAction.cancelLabel ?? "取消草稿并继续"}
              </button>
              <button
                type="button"
                disabled={!draftState.canCommit}
                onClick={() => runDraftCommand("commit")}
                className="inline-flex h-10 items-center justify-center rounded-lg bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {pendingDraftAction.commitLabel ?? "提交草稿并继续"}
              </button>
            </div>
          </div>
        </div>
      )}

      {pendingDirtyAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-md rounded-lg border border-line bg-white p-5 shadow-xl">
            <h2 className="text-base font-semibold text-ink">{pendingDirtyAction.title}</h2>
            <p className="mt-2 text-sm text-gray-600">{pendingDirtyAction.description}</p>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setPendingDirtyAction(null)}
                className="inline-flex h-10 items-center justify-center rounded-lg border border-line px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handlePendingDirtyDiscard}
                className="inline-flex h-10 items-center justify-center rounded-lg border border-amber-200 px-4 text-sm font-medium text-amber-700 hover:bg-amber-50"
              >
                放弃修改
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => void handlePendingDirtySave()}
                className="inline-flex h-10 items-center justify-center rounded-lg bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {saving ? "保存中" : "保存并继续"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
