import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  CircleSlash2,
  HelpCircle,
  Image as ImageIcon,
  ListFilter,
  Loader2,
  RefreshCw,
  Tags
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  createAnnotationClass,
  getDataset,
  getSample,
  getSampleFileUrl,
  getSampleNavigation,
  listAnnotationClasses,
  listSampleAnnotations,
  replaceSampleAnnotations,
  syncAnnotationClassesToSampleTags
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
  AnnotationClass,
  AnnotationObject,
  AnnotationQueueScope,
  AnnotationReplaceItem,
  AnnotationReplaceRequest,
  AnnotationShapeType,
  Dataset,
  ReviewStatus,
  Sample,
  SampleNavigationResponse,
  SampleQuery
} from "../types/dataset";
import { annotationQueueCopy, buildQueueChangeParams, writeAnnotationQueue } from "../utils/annotationQueue";
import { annotationProgressCopy, reviewStatusCopy } from "../utils/workflow";

const EMPTY_DRAFT_STATE: AnnotationDraftState = { active: false, shapeType: null, canCommit: false };
const AUTO_SAVE_ON_NAVIGATION_KEY = "dataset-manager.annotation.autoSaveOnNavigation";
const SAMPLE_SORT_COPY: Record<string, string> = {
  created_at: "创建时间",
  filename: "文件名",
  file_size: "文件大小",
  updated_at: "更新时间"
};

type DeferredAction = () => void | Promise<void>;
type AnnotationSaveMode = NonNullable<AnnotationReplaceRequest["save_mode"]>;

interface PendingAction {
  title: string;
  description: string;
  action: DeferredAction;
  commitLabel?: string;
  cancelLabel?: string;
}

interface KeyboardShortcutActions {
  requestSave: () => void;
  saveAndNext: () => void;
  undoAndMarkDirty: () => void;
  redoAndMarkDirty: () => void;
  changeTool: (tool: AnnotationTool) => void;
  switchPrevious: () => void;
  switchNext: () => void;
}

const ANNOTATION_CLASS_COLORS = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#059669", "#0891b2", "#4f46e5"];

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
  const [annotationClasses, setAnnotationClasses] = useState<AnnotationClass[]>([]);
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
  const [workspaceLoadFailed, setWorkspaceLoadFailed] = useState(false);
  const [draftState, setDraftState] = useState<AnnotationDraftState>(EMPTY_DRAFT_STATE);
  const [draftCommand, setDraftCommand] = useState<AnnotationDraftCommand | null>(null);
  const [focusCommand, setFocusCommand] = useState<AnnotationFocusCommand | null>(null);
  const [pendingDraftAction, setPendingDraftAction] = useState<PendingAction | null>(null);
  const [pendingDirtyAction, setPendingDirtyAction] = useState<PendingAction | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [creatingClass, setCreatingClass] = useState(false);
  const [lastAdvanceMs, setLastAdvanceMs] = useState<number | null>(null);
  const [sessionCompletedCount, setSessionCompletedCount] = useState(0);
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
  const annotationCacheRef = useRef<Map<number, Promise<AnnotationObject[]>>>(new Map());
  const imagePrefetchRef = useRef<Map<number, HTMLImageElement>>(new Map());
  const pendingAdvanceRef = useRef<{ sampleId: number | null; startedAt: number } | null>(null);
  const pendingNavigationStatusRef = useRef<{ sampleId: number | null; message: string } | null>(null);
  const workspaceRequestIdRef = useRef(0);
  const guardFocusReturnRef = useRef<HTMLElement | null>(null);

  const queueScope = useMemo<AnnotationQueueScope>(() => {
    const value = new URLSearchParams(searchParamsText).get("queue");
    return value === "all_pending" || value === "current_split" ? value : "current_filter";
  }, [searchParamsText]);

  const navigationQuery = useMemo(() => {
    const context = new URLSearchParams(searchParamsText);
    const contextFileStatus = context.get("fileStatus") || "";
    return {
      search: context.get("search") || undefined,
      fileStatus: contextFileStatus === "duplicate" ? "duplicate" : "normal",
      tag: context.get("tag") || undefined,
      split:
        queueScope === "current_split"
          ? context.get("queueSplit") || undefined
          : context.get("split") || undefined,
      reviewStatus: context.get("reviewStatus") || undefined,
      annotationProgress: (context.get("annotationProgress") || undefined) as SampleQuery["annotationProgress"],
      queueScope,
      sortBy: context.get("sortBy") || "created_at",
      sortOrder: context.get("sortOrder") === "asc" ? ("asc" as const) : ("desc" as const)
    };
  }, [queueScope, searchParamsText]);

  const activeAnnotationClass = useMemo(
    () =>
      annotationClasses.find(
        (annotationClass) => annotationClass.name.toLowerCase() === activeLabel.trim().toLowerCase()
      ) ?? null,
    [activeLabel, annotationClasses]
  );
  const previousSample = navigation?.previous_sample ?? null;
  const nextSample = navigation?.next_sample ?? null;
  const sampleCompleted =
    sample?.annotation_progress === "completed_empty"
    || sample?.annotation_progress === "completed_with_objects";
  const currentPendingQueueCompleted = queueScope !== "current_filter" && sampleCompleted;
  const navigationLabel =
    !navigation || navigation.total === 0
      ? "无可导航图片"
      : currentPendingQueueCompleted
        ? "当前样本已完成"
        : navigation.current_index !== null
          ? `${navigation.current_index + 1} / ${navigation.total}`
          : "不在当前筛选结果";
  const queueSplit = new URLSearchParams(searchParamsText).get("queueSplit") || sample?.split || "unassigned";
  const queueLabel = queueScope === "current_split"
    ? `${annotationQueueCopy.current_split} · ${queueSplit === "unassigned" ? "未划分" : queueSplit}`
    : annotationQueueCopy[queueScope];
  const queueDescription = useMemo(() => {
    const sortLabel = SAMPLE_SORT_COPY[navigationQuery.sortBy] ?? navigationQuery.sortBy;
    const sortDescription = `${sortLabel}${navigationQuery.sortOrder === "asc" ? "正序" : "倒序"}`;
    if (queueScope === "all_pending") {
      return `正常图片 · 未开始/处理中 · ${sortDescription}`;
    }
    if (queueScope === "current_split") {
      const splitLabel = queueSplit === "unassigned" ? "未划分" : queueSplit;
      return `${splitLabel} · 正常图片 · 未开始/处理中 · ${sortDescription}`;
    }
    const context: string[] = [
      navigationQuery.fileStatus === "duplicate" ? "重复文件" : "正常图片"
    ];
    if (navigationQuery.search) {
      context.push(`搜索“${navigationQuery.search}”`);
    }
    if (navigationQuery.tag) {
      context.push(`标签 ${navigationQuery.tag}`);
    }
    if (navigationQuery.split) {
      context.push(navigationQuery.split === "unassigned" ? "未划分" : `划分 ${navigationQuery.split}`);
    }
    if (navigationQuery.reviewStatus && navigationQuery.reviewStatus in reviewStatusCopy) {
      context.push(reviewStatusCopy[navigationQuery.reviewStatus as ReviewStatus]);
    }
    if (navigationQuery.annotationProgress) {
      context.push(annotationProgressCopy[navigationQuery.annotationProgress]);
    }
    context.push(sortDescription);
    return context.join(" · ");
  }, [navigationQuery, queueScope, queueSplit]);
  const queueRemaining = navigation?.remaining ?? 0;
  const hasQueueContinuation = queueRemaining > 0;
  const hasUnsavedState = dirty || draftState.active;
  const allowedShapeTypes = useMemo<AnnotationShapeType[]>(
    () => dataset?.task_capabilities.allowed_shape_types ?? [],
    [dataset?.task_capabilities.allowed_shape_types]
  );
  const geometryTask = dataset?.task_capabilities.supported === true && dataset.task_capabilities.annotation_mode === "geometry";
  const progressLabel = dataset?.task_type === "segmentation" ? "分割进度" : "检测进度";

  const setClean = useCallback(() => {
    dirtyRef.current = false;
    setDirty(false);
  }, []);

  const markDirty = useCallback(() => {
    dirtyRef.current = true;
    setDirty(true);
  }, []);

  const loadAnnotations = useCallback((sampleId: number) => {
    const cached = annotationCacheRef.current.get(sampleId);
    if (cached) {
      return cached;
    }
    const request = listSampleAnnotations(sampleId).catch((requestError) => {
      annotationCacheRef.current.delete(sampleId);
      throw requestError;
    });
    annotationCacheRef.current.set(sampleId, request);
    while (annotationCacheRef.current.size > 4) {
      const oldestKey = annotationCacheRef.current.keys().next().value;
      if (typeof oldestKey !== "number") {
        break;
      }
      annotationCacheRef.current.delete(oldestKey);
    }
    return request;
  }, []);

  useEffect(() => {
    sampleRef.current = sample;
  }, [sample]);

  const loadWorkspace = useCallback(async () => {
    const requestId = workspaceRequestIdRef.current + 1;
    workspaceRequestIdRef.current = requestId;
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
    setWorkspaceLoadFailed(false);
    try {
      const targetSampleId = Number.isFinite(requestedSampleId) && requestedSampleId > 0 ? requestedSampleId : null;
      const [nextDataset, nextAnnotationClasses, nextNavigation] = await Promise.all([
        getDataset(datasetId),
        listAnnotationClasses(datasetId),
        getSampleNavigation({
          datasetId,
          sampleId: targetSampleId,
          search: navigationQuery.search,
          fileStatus: navigationQuery.fileStatus,
          tag: navigationQuery.tag,
          split: navigationQuery.split,
          reviewStatus: navigationQuery.reviewStatus,
          annotationProgress: navigationQuery.annotationProgress,
          queueScope: navigationQuery.queueScope,
          sortBy: navigationQuery.sortBy,
          sortOrder: navigationQuery.sortOrder
        })
      ]);
      if (requestId !== workspaceRequestIdRef.current) {
        return;
      }
      const nextNavigationSample = nextNavigation.current_sample;
      setDataset(nextDataset);
      setAnnotationClasses(nextAnnotationClasses);
      setNavigation(nextNavigation);
      if (nextDataset.task_capabilities.annotation_mode !== "geometry" || !nextDataset.task_capabilities.supported) {
        setSample(nextNavigationSample);
        reset([]);
        setClean();
        setDraftState(EMPTY_DRAFT_STATE);
        return;
      }
      if (!targetSampleId && nextNavigationSample) {
        const nextParams = new URLSearchParams(searchParamsText);
        nextParams.set("sample", String(nextNavigationSample.id));
        setSearchParams(nextParams, { replace: true });
      }
      if (!nextNavigationSample && targetSampleId && new URLSearchParams(searchParamsText).get("resume") === "1") {
        const nextParams = new URLSearchParams(searchParamsText);
        nextParams.delete("sample");
        setSearchParams(nextParams, { replace: true });
        return;
      }
      if (!nextNavigationSample) {
        setSample(null);
        reset([]);
        setClean();
        setDraftState(EMPTY_DRAFT_STATE);
        setStatus("当前队列没有可处理样本");
        setError("当前标注队列没有可处理的正常图片样本");
        return;
      }
      const [nextSample, nextAnnotations] = await Promise.all([
        getSample(nextNavigationSample.id),
        loadAnnotations(nextNavigationSample.id)
      ]);
      if (requestId !== workspaceRequestIdRef.current) {
        return;
      }
      setSample(nextSample);
      reset(normalizeObjects(nextAnnotations));
      const requestedAnnotationId = Number(new URLSearchParams(searchParamsText).get("annotation"));
      const requestedAnnotation = Number.isFinite(requestedAnnotationId)
        ? nextAnnotations.find((annotation) => annotation.id === requestedAnnotationId)
        : undefined;
      const nextActiveObject = requestedAnnotation ?? nextAnnotations[0];
      setActiveObjectId(nextActiveObject?.client_id ?? null);
      setActiveLabel(nextActiveObject?.label ?? nextAnnotationClasses[0]?.name ?? "object");
      setClean();
      setDraftState(EMPTY_DRAFT_STATE);
      setDraftCommand(null);
      setFocusCommand(null);
      if (requestedAnnotation) {
        const nextCommand = { id: focusCommandIdRef.current + 1, clientId: requestedAnnotation.client_id };
        focusCommandIdRef.current = nextCommand.id;
        setFocusCommand(nextCommand);
      }
      setPendingDraftAction(null);
      setPendingDirtyAction(null);
      if (!isAnnotatableImage(nextSample)) {
        setError("当前样本不是正常状态的图片，暂不支持几何标注");
      }
      const pendingAdvance = pendingAdvanceRef.current;
      if (pendingAdvance && (pendingAdvance.sampleId === null || pendingAdvance.sampleId === nextSample.id)) {
        setLastAdvanceMs(Math.round(performance.now() - pendingAdvance.startedAt));
        pendingAdvanceRef.current = null;
        setStatus("已打开下一张，可以继续标注");
      } else {
        pendingAdvanceRef.current = null;
        const pendingNavigationStatus = pendingNavigationStatusRef.current;
        if (
          pendingNavigationStatus
          && (pendingNavigationStatus.sampleId === null || pendingNavigationStatus.sampleId === nextSample.id)
        ) {
          pendingNavigationStatusRef.current = null;
          setStatus(pendingNavigationStatus.message);
        } else {
          pendingNavigationStatusRef.current = null;
          setStatus("准备就绪");
        }
      }
    } catch {
      if (requestId === workspaceRequestIdRef.current) {
        pendingAdvanceRef.current = null;
        pendingNavigationStatusRef.current = null;
        setWorkspaceLoadFailed(true);
        setStatus("标注工作区加载失败");
        setError("标注工作区加载失败");
      }
    } finally {
      if (requestId === workspaceRequestIdRef.current) {
        setLoading(false);
        setSampleLoading(false);
        setNavigationLoading(false);
      }
    }
  }, [datasetId, loadAnnotations, navigationQuery, requestedSampleId, reset, searchParamsText, setClean, setSearchParams]);

  useEffect(() => {
    void loadWorkspace();
    return () => {
      workspaceRequestIdRef.current += 1;
    };
  }, [loadWorkspace]);

  useEffect(() => {
    try {
      window.localStorage.setItem(AUTO_SAVE_ON_NAVIGATION_KEY, String(autoSaveOnNavigation));
    } catch {
      // Ignore storage failures; the toggle still works for the current session.
    }
  }, [autoSaveOnNavigation]);

  useEffect(() => {
    if (!sample) {
      return;
    }
    writeAnnotationQueue(datasetId, sample.id, new URLSearchParams(searchParamsText));
  }, [datasetId, sample, searchParamsText]);

  useEffect(() => {
    const adjacentSamples = [navigation?.previous_sample, navigation?.next_sample].filter(
      (item): item is Sample => Boolean(item)
    );
    for (const adjacentSample of adjacentSamples) {
      if (!imagePrefetchRef.current.has(adjacentSample.id)) {
        const image = new Image();
        image.src = getSampleFileUrl(adjacentSample.id);
        imagePrefetchRef.current.set(adjacentSample.id, image);
      }
      void loadAnnotations(adjacentSample.id).catch(() => undefined);
    }
    while (imagePrefetchRef.current.size > 4) {
      const oldestKey = imagePrefetchRef.current.keys().next().value;
      if (typeof oldestKey !== "number") {
        break;
      }
      imagePrefetchRef.current.delete(oldestKey);
    }
  }, [loadAnnotations, navigation?.next_sample, navigation?.previous_sample]);

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
      if (event.key === "Escape" && pendingDraftAction) {
        event.preventDefault();
        closeGuardDialog("draft");
        return;
      }
      if (event.key === "Escape" && pendingDirtyAction) {
        event.preventDefault();
        closeGuardDialog("dirty");
        return;
      }
      if (event.key === "Escape" && helpOpen) {
        event.preventDefault();
        setHelpOpen(false);
        return;
      }
      if (pendingDraftAction || pendingDirtyAction) {
        return;
      }
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
      } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        actions.saveAndNext();
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
  }, [helpOpen, pendingDirtyAction, pendingDraftAction]);

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
        const matchedClass = annotationClasses.find(
          (annotationClass) => annotationClass.name.toLowerCase() === object.label.trim().toLowerCase()
        );
        return {
          label: object.label.trim(),
          class_id: matchedClass?.id ?? object.class_id ?? null,
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

  async function handleSave(saveMode: AnnotationSaveMode = "draft"): Promise<boolean> {
    if (!sample || saving) {
      return false;
    }
    if (saveMode === "draft" && !dirtyRef.current) {
      setStatus("没有需要保存的修改");
      return true;
    }
    setSaving(true);
    setError(null);
    setWorkspaceLoadFailed(false);
    try {
      let saved: AnnotationObject[];
      try {
        saved = await replaceSampleAnnotations(sample.id, {
          annotations: saveMode === "confirm_empty" ? [] : buildSavePayload(),
          save_mode: saveMode
        });
      } catch {
        setStatus("保存失败，修改仍保留，可修正后重试");
        setError("标注保存失败；当前修改仍保留，请检查对象类别、坐标或服务连接后重试");
        return false;
      }
      annotationCacheRef.current.set(sample.id, Promise.resolve(saved));
      reset(normalizeObjects(saved));
      setActiveObjectId(saved[0]?.client_id ?? null);
      setClean();
      setSample((current) => current ? {
        ...current,
        annotation_progress:
          saveMode === "complete"
            ? "completed_with_objects"
            : saveMode === "confirm_empty"
              ? "completed_empty"
              : "in_progress",
        review_status:
          saveMode !== "draft" && current.review_status === "not_reviewed"
            ? "in_review"
            : current.review_status
      } : current);
      if (
        !sampleCompleted
        && (saveMode === "complete" || saveMode === "confirm_empty")
      ) {
        setSessionCompletedCount((current) => current + 1);
      }
      setStatus(
        saveMode === "complete"
          ? "已标记为完成（有对象）"
          : saveMode === "confirm_empty"
            ? "已确认无目标"
            : "标注草稿已保存"
      );
      try {
        const [nextSample, nextAnnotationClasses] = await Promise.all([
          getSample(sample.id),
          listAnnotationClasses(datasetId)
        ]);
        setSample(nextSample);
        setAnnotationClasses(nextAnnotationClasses);
      } catch {
        setWorkspaceLoadFailed(true);
        setStatus("标注已保存，状态刷新未完成");
        setError("标注已保存，但工作区状态刷新失败；可重新加载确认最新状态");
      }
      return true;
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateActiveClass() {
    const name = activeLabel.trim();
    if (!name || creatingClass || annotationClasses.some((item) => item.name.toLowerCase() === name.toLowerCase())) {
      return;
    }
    setCreatingClass(true);
    setError(null);
    try {
      const created = await createAnnotationClass(datasetId, {
        name,
        color: ANNOTATION_CLASS_COLORS[annotationClasses.length % ANNOTATION_CLASS_COLORS.length]
      });
      setAnnotationClasses((current) => [...current, created].sort((left, right) => left.name.localeCompare(right.name)));
      setStatus(`已新建对象类别“${created.name}”`);
    } catch {
      setError("对象类别创建失败，请确认名称没有重复");
    } finally {
      setCreatingClass(false);
    }
  }

  async function handleSyncClassesToTags() {
    if (!sample || saving) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await syncAnnotationClassesToSampleTags(sample.id);
      const added = result.added_tags.length;
      setSample(await getSample(sample.id));
      setStatus(added > 0 ? `已追加 ${added} 个样本标签` : "样本标签已包含全部对象类别");
    } catch {
      setError("同步失败；对象类别与样本标签仍保持独立，请稍后重试");
    } finally {
      setSaving(false);
    }
  }

  function requestDirtyAction(action: DeferredAction, title: string, description: string) {
    if (dirtyRef.current) {
      if (!guardFocusReturnRef.current?.isConnected) {
        guardFocusReturnRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      }
      setPendingDirtyAction({ title, description, action });
      return;
    }
    guardFocusReturnRef.current = null;
    void action();
  }

  function requestDraftAction(action: DeferredAction, title: string, description: string, labels?: Pick<PendingAction, "commitLabel" | "cancelLabel">) {
    if (!draftState.active) {
      guardFocusReturnRef.current = null;
      void action();
      return;
    }
    if (!guardFocusReturnRef.current?.isConnected) {
      guardFocusReturnRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    setPendingDraftAction({ title, description, action, ...labels });
  }

  function closeGuardDialog(type: "draft" | "dirty") {
    if (type === "draft") {
      setPendingDraftAction(null);
      actionAfterDraftRef.current = null;
    } else {
      setPendingDirtyAction(null);
    }
    const focusTarget = guardFocusReturnRef.current;
    guardFocusReturnRef.current = null;
    window.setTimeout(() => focusTarget?.focus(), 0);
  }

  function requestSampleNavigationAction(action: DeferredAction) {
    const guardedAction = async () => {
      if (autoSaveOnNavigation && dirtyRef.current) {
        const saved = await handleSave("draft");
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
      () => void handleSave("draft"),
      "处理绘制中的对象",
      "保存前需要先提交或取消当前正在绘制的对象。",
      { commitLabel: "提交草稿并保存", cancelLabel: "取消草稿并保存" }
    );
  }

  function requestSaveAndNext() {
    requestDraftAction(
      () => void handleSaveAndNext(),
      "处理绘制中的对象",
      "推进到下一张前需要先提交或取消当前正在绘制的对象。",
      { commitLabel: "提交对象并继续", cancelLabel: "取消对象并继续" }
    );
  }

  async function handleCompleteCurrent() {
    if (!sample) {
      setStatus("当前队列没有可处理样本");
      return;
    }
    if (sampleCompleted && !dirtyRef.current) {
      setStatus("当前样本已经完成，无需重复保存");
      return;
    }
    await handleSave(objects.length > 0 ? "complete" : "confirm_empty");
  }

  async function handleSaveAndNext() {
    if (!sample) {
      setStatus("当前队列没有可处理样本");
      return;
    }
    const target = nextSample;
    const shouldWrapToQueueStart = !target && hasQueueContinuation;
    const startedAt = performance.now();
    if (!sampleCompleted || dirtyRef.current) {
      const saved = await handleSave(objects.length > 0 ? "complete" : "confirm_empty");
      if (!saved) {
        return;
      }
    }
    if (!target && !shouldWrapToQueueStart) {
      setLastAdvanceMs(Math.round(performance.now() - startedAt));
      setStatus("当前队列已完成");
      setNavigation((current) => current ? { ...current, remaining: 0 } : current);
      return;
    }
    pendingAdvanceRef.current = { sampleId: target?.id ?? null, startedAt };
    setStatus("已完成，正在打开队列下一张");
    if (target) {
      setSampleInUrl(target.id);
    } else {
      setQueueStartInUrl();
    }
  }

  function handleQueueScopeChange(nextScope: AnnotationQueueScope) {
    if (nextScope === queueScope) {
      return;
    }
    const changeQueue = () => {
      const nextParams = buildQueueChangeParams(searchParams, nextScope, sample?.split);
      setSearchParams(nextParams);
    };
    requestNavigationAction(
      changeQueue,
      "切换标注队列前，请选择保存当前标注、放弃修改或取消切换。"
    );
  }

  function handleToolChange(nextTool: AnnotationTool) {
    if (
      nextTool !== "select"
      && nextTool !== "pan"
      && !allowedShapeTypes.includes(nextTool as AnnotationShapeType)
    ) {
      setStatus(`当前${dataset?.task_capabilities.label ?? "任务"}不提供此绘制工具`);
      return;
    }
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
    const saved = await handleSave("draft");
    if (!saved) {
      return;
    }
    setPendingDirtyAction(null);
    guardFocusReturnRef.current = null;
    await pending.action();
  }

  function handlePendingDirtyDiscard() {
    const pending = pendingDirtyAction;
    if (!pending) {
      return;
    }
    setPendingDirtyAction(null);
    setClean();
    guardFocusReturnRef.current = null;
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

  function setQueueStartInUrl() {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("sample");
    nextParams.delete("annotation");
    setSearchParams(nextParams);
  }

  function switchSample(target: Sample | null) {
    if (!target || target.id === sample?.id) {
      return;
    }
    requestSampleNavigationAction(() => setSampleInUrl(target.id));
  }

  function switchToNextQueueSample() {
    if (!nextSample && !hasQueueContinuation) {
      setStatus("当前队列没有其他样本");
      return;
    }
    const target = nextSample;
    requestSampleNavigationAction(() => {
      pendingNavigationStatusRef.current = {
        sampleId: target?.id ?? null,
        message: "已跳过上一张，样本完成状态未改变"
      };
      if (target) {
        setSampleInUrl(target.id);
      } else {
        setQueueStartInUrl();
      }
    });
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

  function trapDialogFocus(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") {
      return;
    }
    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
    );
    if (focusable.length === 0) {
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  keyboardShortcutsRef.current = {
    requestSave,
    saveAndNext: requestSaveAndNext,
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
    switchNext: switchToNextQueueSample
  };

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-canvas text-gray-600">
        <Loader2 className="mr-2 animate-spin" size={18} />
        正在加载标注工作区
      </main>
    );
  }

  if (dataset && !geometryTask) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-canvas px-5">
        <section className="w-full max-w-xl rounded-2xl border border-line bg-white p-7 text-center shadow-soft">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-gray-100 text-gray-700">
            {dataset.task_type === "classification" ? <Tags size={24} /> : <CircleSlash2 size={24} />}
          </div>
          <div className="mt-4 text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">
            {dataset.task_capabilities.label}
          </div>
          <h1 className="mt-2 text-xl font-semibold text-ink">
            {dataset.task_type === "classification" ? "此任务使用样本标签整理类别" : "当前任务类型暂不支持标注工作区"}
          </h1>
          <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-gray-600">
            {dataset.task_type === "classification"
              ? "分类整理不需要绘制几何对象。请返回数据集，在样本详情或批量工具中添加标签，并使用 CSV 标签表导出。"
              : dataset.task_capabilities.unsupported_reason}
          </p>
          <button
            type="button"
            onClick={() => navigate(`/datasets/${datasetId}`)}
            className="mt-6 inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-5 text-sm font-medium text-white hover:bg-gray-800"
          >
            <ArrowLeft size={17} />
            返回数据集
          </button>
        </section>
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
                title="查看上一张（不改变完成状态）"
                aria-label="查看上一张（不改变完成状态）"
                disabled={!previousSample || navigationLoading}
                onClick={() => switchSample(previousSample)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
              >
                <ChevronLeft size={18} />
              </button>
              <button
                type="button"
                title="跳过当前，查看队列下一张"
                aria-label="跳过当前，查看队列下一张"
                disabled={(!nextSample && !hasQueueContinuation) || navigationLoading}
                onClick={switchToNextQueueSample}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
              >
                <ChevronRight size={18} />
              </button>
            </div>
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2 text-sm text-gray-500">
                <span className="truncate">{dataset?.name ?? "数据集"}</span>
                {dataset && (
                  <span className="shrink-0 rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                    {dataset.task_capabilities.label}
                  </span>
                )}
                <span aria-live="polite" className="shrink-0 rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                  {navigationLoading ? "加载队列" : `${queueLabel} · ${navigationLabel}`}
                </span>
              </div>
              <h1 className="truncate text-lg font-semibold text-ink">{sample?.filename ?? "未选择样本"}</h1>
            </div>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
            {sample && (
              <span className="hidden min-w-0 max-w-full items-center gap-2 rounded-lg border border-line bg-gray-50 px-3 py-2 text-gray-600 md:inline-flex lg:max-w-md">
                <ImageIcon className="shrink-0" size={16} />
                <span className="truncate">{sample.relative_path}</span>
              </span>
            )}
            <label
              title={`队列条件：${queueDescription}`}
              className="inline-flex min-h-10 w-full min-w-0 items-center gap-2 rounded-lg border border-line bg-white px-3 py-1.5 text-gray-700 sm:w-auto"
            >
              <ListFilter size={16} className="shrink-0" />
              <span className="sr-only">标注队列</span>
              <span className="flex min-w-0 flex-1 flex-col sm:flex-none">
                <select
                  aria-label="标注队列范围"
                  value={queueScope}
                  onChange={(event) => handleQueueScopeChange(event.target.value as AnnotationQueueScope)}
                  className="max-w-40 bg-transparent text-sm font-medium outline-none"
                >
                  <option value="all_pending">{annotationQueueCopy.all_pending}</option>
                  <option value="current_filter">{annotationQueueCopy.current_filter}</option>
                  <option value="current_split" disabled={!sample && queueScope !== "current_split"}>
                    {annotationQueueCopy.current_split}
                  </option>
                </select>
                <span aria-label={`队列条件：${queueDescription}`} className="max-w-56 truncate text-[11px] leading-4 text-gray-400">
                  {queueDescription}
                </span>
              </span>
              <span className="whitespace-nowrap border-l border-line pl-2 text-xs text-gray-500">
                剩余 {queueRemaining}
              </span>
            </label>
            <span
              aria-live="polite"
              className={`min-w-24 rounded-lg px-3 py-2 text-center ${
                hasUnsavedState ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"
              }`}
            >
              {saving ? "保存中" : sampleLoading ? "加载中" : draftState.active ? "有未提交草稿" : dirty ? "有未保存修改" : "已保存"}
            </span>
            {sample && (
              <span className="rounded-lg border border-line bg-white px-2 py-2 text-gray-700 sm:px-3">
                <span className="hidden sm:inline">{progressLabel}：</span>
                {annotationProgressCopy[sample.annotation_progress]}
              </span>
            )}
            <label
              title="切换样本时自动保存草稿"
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-line bg-white px-2 text-gray-700 sm:px-3"
            >
              <input
                type="checkbox"
                aria-label="切换样本时自动保存草稿"
                checked={autoSaveOnNavigation}
                onChange={(event) => setAutoSaveOnNavigation(event.target.checked)}
                className="h-4 w-4 rounded border-line text-gray-900"
              />
              <span className="hidden sm:inline">切换自动保存</span>
            </label>
            <div className="relative">
              <button
                type="button"
                title="快捷键"
                aria-expanded={helpOpen}
                aria-haspopup="dialog"
                onClick={() => setHelpOpen((value) => !value)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-700 hover:bg-gray-50"
              >
                <HelpCircle size={18} />
              </button>
              {helpOpen && (
                <div role="dialog" aria-label="快捷键帮助" className="absolute right-0 top-12 z-30 w-64 rounded-lg border border-line bg-white p-3 text-xs text-gray-600 shadow-lg">
                  <div className="mb-2 text-sm font-semibold text-ink">快捷键</div>
                  <div className="grid grid-cols-[72px_1fr] gap-x-3 gap-y-1">
                    <span className="font-medium text-gray-900">V</span>
                    <span>选择</span>
                    {allowedShapeTypes.includes("rectangle") && (
                      <>
                        <span className="font-medium text-gray-900">R</span>
                        <span>矩形</span>
                      </>
                    )}
                    {allowedShapeTypes.includes("polygon") && (
                      <>
                        <span className="font-medium text-gray-900">P</span>
                        <span>多边形</span>
                      </>
                    )}
                    <span className="font-medium text-gray-900">H</span>
                    <span>平移</span>
                    <span className="font-medium text-gray-900">[ / ]</span>
                    <span>上一张 / 跳过到下一张</span>
                    <span className="font-medium text-gray-900">Ctrl+S</span>
                    <span>保存草稿</span>
                    <span className="font-medium text-gray-900">Ctrl+Enter</span>
                    <span>完成并下一张</span>
                    <span className="font-medium text-gray-900">Delete</span>
                    <span>删除当前对象</span>
                    <span className="font-medium text-gray-900">Esc</span>
                    <span>取消绘制中草稿</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {error && (
        <div role="alert" className="flex shrink-0 items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          <span>{error}</span>
          {workspaceLoadFailed && (
            <button
              type="button"
              onClick={() => void loadWorkspace()}
              disabled={loading || navigationLoading}
              className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-red-200 bg-white px-3 text-xs font-semibold text-red-700 transition hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={14} />
              重新加载工作区
            </button>
          )}
        </div>
      )}
      <section className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <AnnotationToolbar
          tool={tool}
          allowedShapeTypes={allowedShapeTypes}
          canUndo={canUndo}
          canRedo={canRedo}
          onToolChange={handleToolChange}
          onUndo={() => {
            undo();
            markDirty();
          }}
          onRedo={() => {
            redo();
            markDirty();
          }}
        />
        {sample && isAnnotatableImage(sample) ? (
          <AnnotationCanvas
            imageUrl={getSampleFileUrl(sample.id)}
            objects={objects}
            activeObjectId={activeObjectId}
            tool={tool}
            activeLabel={activeLabel}
            activeClassId={activeAnnotationClass?.id ?? null}
            annotationClasses={annotationClasses}
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
          annotationClasses={annotationClasses}
          activeLabel={activeLabel}
          creatingClass={creatingClass}
          dirty={dirty}
          saving={saving}
          draftActive={draftState.active}
          hasQueueContinuation={hasQueueContinuation}
          sampleAvailable={Boolean(sample && isAnnotatableImage(sample))}
          sampleCompleted={sampleCompleted}
          onSelect={handleObjectSelect}
          onUpdate={updateObject}
          onDelete={deleteObject}
          onActiveLabelChange={setActiveLabel}
          onCreateClass={() => void handleCreateActiveClass()}
          onSaveDraft={requestSave}
          onCompleteCurrent={() => void handleCompleteCurrent()}
          onSaveAndNext={requestSaveAndNext}
          onSyncClassesToTags={() => void handleSyncClassesToTags()}
        />
      </section>

      <footer role="status" aria-live="polite" aria-atomic="true" className="shrink-0 border-t border-line bg-white px-4 py-2 text-xs text-gray-500">
        <div className="flex items-center justify-between gap-3">
          <span className="truncate">{status}</span>
          <span className="shrink-0">
            本次完成 {sessionCompletedCount}
            {lastAdvanceMs !== null ? ` · 上次推进 ${lastAdvanceMs} ms` : " · 快捷键在右上角帮助中查看"}
          </span>
        </div>
      </footer>

      {pendingDraftAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
          <div role="dialog" aria-modal="true" aria-labelledby="annotation-draft-dialog-title" onKeyDown={trapDialogFocus} className="w-full max-w-md rounded-lg border border-line bg-white p-5 shadow-xl">
            <h2 id="annotation-draft-dialog-title" className="text-base font-semibold text-ink">{pendingDraftAction.title}</h2>
            <p className="mt-2 text-sm text-gray-600">{pendingDraftAction.description}</p>
            {!draftState.canCommit && (
              <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                当前草稿还不满足提交条件，只能取消草稿或返回继续绘制。
              </p>
            )}
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                autoFocus
                onClick={() => closeGuardDialog("draft")}
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
          <div role="dialog" aria-modal="true" aria-labelledby="annotation-dirty-dialog-title" onKeyDown={trapDialogFocus} className="w-full max-w-md rounded-lg border border-line bg-white p-5 shadow-xl">
            <h2 id="annotation-dirty-dialog-title" className="text-base font-semibold text-ink">{pendingDirtyAction.title}</h2>
            <p className="mt-2 text-sm text-gray-600">{pendingDirtyAction.description}</p>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                autoFocus
                onClick={() => closeGuardDialog("dirty")}
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
