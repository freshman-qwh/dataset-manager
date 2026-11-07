import axios from "axios";
import {
  ArrowLeft,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  ListChecks,
  Loader2,
  Moon,
  Plus,
  RotateCcw,
  Settings2,
  Sun,
  X,
  ZoomIn,
  ZoomOut
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  createDefectType,
  getDataset,
  getSampleFileUrl,
  getSampleTriage,
  getTriageNavigation,
  getTriagePolicy,
  getTriageStats,
  listDefectTypes,
  previewTriagePolicy,
  replaceSampleTriage,
  updateTriagePolicy
} from "../api/client";
import type { Dataset, Sample } from "../types/dataset";
import type {
  DefectSeverity,
  DefectType,
  NgGrouping,
  OkGrade,
  SampleTriage,
  SampleTriageWrite,
  TriageNavigation,
  TriagePolicy,
  TriagePolicyImpactPreview,
  TriagePolicyValues,
  TriageQueueScope,
  TriageStats,
  TriageStatus
} from "../types/triage";
import TriagePolicyModal from "../components/TriagePolicyModal";
import ReferenceCasesPanel from "../components/ReferenceCasesPanel";
import TriageReasonChips from "../components/TriageReasonChips";
import WorkpieceViewsPanel from "../components/WorkpieceViewsPanel";
import Modal from "../components/Modal";
import { updateValidationReview } from "../api/validation";
import { okGradeCopy } from "../utils/uiCopy";
import { getWorkNavigation, getWorkScope, getWorkState, type WorkScopeQuery } from "../api/triageWork";
import { completeWorkSample, readTriageWork, reconcileWork, workIds, workQuery, writeTriageWork, type TriageWork, type WorkView } from "../utils/triageWork";

const QUEUE_LABELS: Record<TriageQueueScope, string> = {
  untriaged: "未分拣",
  pending: "待定复看",
  current_filter: "全部图片",
  current_split: "当前划分"
};

const QUEUE_OPTIONS: TriageQueueScope[] = [
  "untriaged",
  "pending",
  "current_filter",
  "current_split"
];

const STATUS_LABELS: Record<TriageStatus, string> = {
  untriaged: "未分拣",
  pending: "待定",
  ok: "OK",
  ng: "NG"
};

const SEVERITY_LABELS: Record<DefectSeverity, string> = {
  mild: "轻微",
  moderate: "中等",
  severe: "严重"
};

const NG_GROUPING_DESCRIPTIONS: Record<NgGrouping, string> = {
  none: "统一判为异常，不再填写类别或程度",
  defect_type: "判为异常后选择缺陷类别",
  severity: "判为异常后选择轻微、中等或严重",
  defect_type_and_severity: "判为异常后填写缺陷类别和严重程度"
};

interface TriageDraft {
  status: TriageStatus;
  okGrade: OkGrade | null;
  severity: DefectSeverity | null;
  defectTypeIds: number[];
  primaryDefectTypeId: number | null;
  note: string;
}

interface UndoRecord {
  sample: Sample;
  before: SampleTriage;
  savedVersion: number;
}

type CanvasTone = "dark" | "light";
type TriageToastTone = "success" | "info";
type ResultTone = "untriaged" | "pending" | "ok" | "clear" | "borderline" | "ng";

interface TriageToast {
  id: number;
  message: string;
  tone: TriageToastTone;
  action: "pending" | null;
  exiting: boolean;
}

const RESULT_STYLES: Record<ResultTone, { badge: string; card: string; label: string }> = {
  untriaged: {
    badge: "border-gray-300 bg-white text-gray-700",
    card: "border-gray-200 bg-gray-50",
    label: "text-gray-900"
  },
  pending: {
    badge: "border-violet-300 bg-violet-100 text-violet-900",
    card: "border-violet-200 bg-violet-50",
    label: "text-violet-950"
  },
  ok: {
    badge: "border-emerald-300 bg-emerald-100 text-emerald-900",
    card: "border-emerald-200 bg-emerald-50",
    label: "text-emerald-950"
  },
  clear: {
    badge: "border-emerald-300 bg-emerald-100 text-emerald-900",
    card: "border-emerald-200 bg-emerald-50",
    label: "text-emerald-950"
  },
  borderline: {
    badge: "border-amber-300 bg-amber-100 text-amber-950",
    card: "border-amber-200 bg-amber-50",
    label: "text-amber-950"
  },
  ng: {
    badge: "border-red-300 bg-red-100 text-red-950",
    card: "border-red-200 bg-red-50",
    label: "text-red-950"
  }
};

function resultPresentation(value: SampleTriage | null, splitOk: boolean) {
  if (!value || value.triage_status === "untriaged") {
    return { tone: "untriaged" as const, label: "未分拣" };
  }
  if (value.triage_status === "pending") {
    return { tone: "pending" as const, label: "待定复看" };
  }
  if (value.triage_status === "ng") {
    return { tone: "ng" as const, label: "NG" };
  }
  if (splitOk && value.ok_grade === "clear") {
    return { tone: "clear" as const, label: okGradeCopy.clear };
  }
  if (splitOk && value.ok_grade === "borderline") {
    return { tone: "borderline" as const, label: okGradeCopy.borderline };
  }
  return { tone: "ok" as const, label: "OK" };
}

function canvasToneStorageKey(dataset: Dataset): string {
  return `dataset-manager.triage.canvas.${dataset.id}.${dataset.created_at}`;
}

function blankDraft(): TriageDraft {
  return {
    status: "untriaged",
    okGrade: null,
    severity: null,
    defectTypeIds: [],
    primaryDefectTypeId: null,
    note: ""
  };
}

function draftFromTriage(value: SampleTriage): TriageDraft {
  return {
    status: value.triage_status,
    okGrade: value.ok_grade,
    severity: value.defect_severity,
    defectTypeIds: value.defect_types.map((item) => item.id),
    primaryDefectTypeId: value.primary_defect_type_id,
    note: value.triage_note ?? ""
  };
}

function writeFromTriage(value: SampleTriage, expectedVersion: number): SampleTriageWrite {
  return {
    expected_version: expectedVersion,
    expected_file_hash: value.file_hash,
    triage_status: value.triage_status,
    ok_grade: value.ok_grade,
    defect_severity: value.defect_severity,
    defect_type_ids: value.defect_types.map((item) => item.id),
    primary_defect_type_id: value.primary_defect_type_id,
    triage_note: value.triage_note
  };
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") {
      return detail[0].msg;
    }
  }
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return Boolean(
    element?.isContentEditable
    || element?.tagName === "INPUT"
    || element?.tagName === "TEXTAREA"
    || element?.tagName === "SELECT"
  );
}

export default function TriagePage() {
  const { datasetId } = useParams();
  return <TriageWorkspace key={datasetId} />;
}

function TriageWorkspace() {
  const routeParams = useParams();
  const datasetId = Number(routeParams.datasetId);
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSampleId = Number(searchParams.get("sample")) || null;
  const reviewRun = searchParams.get("review_run") || undefined;
  const reviewReturn = searchParams.get("back") || "";
  const requestedQueue = searchParams.get("queue");
  const queueScope: TriageQueueScope =
    requestedQueue === "pending"
    || requestedQueue === "current_filter"
    || requestedQueue === "current_split"
      ? requestedQueue
      : "untriaged";
  const queueSplit = searchParams.get("split") || undefined;
  const filterStatus = (searchParams.get("status") || undefined) as TriageStatus | undefined;
  const filterOkGrade = (searchParams.get("okGrade") || undefined) as OkGrade | undefined;
  const filterSeverity = (searchParams.get("severity") || undefined) as DefectSeverity | undefined;
  const filterDefectTypeId = Number(searchParams.get("defectType")) || undefined;
  const navigationSampleId = requestedSampleId;
  const [work, setWorkState] = useState<TriageWork | null>(null);
  const [workReady, setWorkReady] = useState(false);
  const [workNotice, setWorkNotice] = useState("");
  const [storageWarning, setStorageWarning] = useState(false);
  const [newWorkIds, setNewWorkIds] = useState<number[]>([]);
  const [checkingWork, setCheckingWork] = useState(false);
  const workRef = useRef(work);
  workRef.current = work;
  const setWork = useCallback((value: TriageWork | null | ((current: TriageWork | null) => TriageWork | null)) => {
    const next = typeof value === "function" ? value(workRef.current) : value;
    workRef.current = next;
    if (next) setStorageWarning(!writeTriageWork(next));
    setWorkState(next);
  }, []);
  const scopeQuery = workQuery(searchParams);
  const activeWork = !reviewRun && work?.query === scopeQuery ? work : null;
  const activeWorkIds = useMemo(() => activeWork ? workIds(activeWork) : null, [activeWork]);
  const activeIdsKey = activeWorkIds?.join(",") ?? "";

  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [policy, setPolicy] = useState<TriagePolicy | null>(null);
  const [policyDraft, setPolicyDraft] = useState<TriagePolicyValues | null>(null);
  const [policyPanelOpen, setPolicyPanelOpen] = useState(false);
  const [policyImpact, setPolicyImpact] = useState<TriagePolicyImpactPreview | null>(null);
  const [policySaving, setPolicySaving] = useState(false);
  const [stats, setStats] = useState<TriageStats | null>(null);
  const [defectTypes, setDefectTypes] = useState<DefectType[]>([]);
  const [navigation, setNavigation] = useState<TriageNavigation | null>(null);
  const [navigationRevision, setNavigationRevision] = useState(0);
  const [triage, setTriage] = useState<SampleTriage | null>(null);
  const [draft, setDraft] = useState<TriageDraft>(blankDraft);
  const [mode, setMode] = useState<"quick" | "detail">("quick");
  const [zoom, setZoom] = useState(1);
  const [imageReady, setImageReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<TriageToast[]>([]);
  const [toastsMuted, setToastsMuted] = useState(false);
  const [canvasTone, setCanvasTone] = useState<CanvasTone>("dark");
  const [undoStack, setUndoStack] = useState<UndoRecord[]>([]);
  const [positionDraft, setPositionDraft] = useState<number | null>(null);
  const [positionInput, setPositionInput] = useState("");
  const [jumping, setJumping] = useState(false);
  const [newDefectName, setNewDefectName] = useState("");
  const [newDefectParent, setNewDefectParent] = useState<number | null>(null);
  const [creatingDefect, setCreatingDefect] = useState(false);
  const [referenceOpen, setReferenceOpen] = useState(false);
  const [workpieceOpen, setWorkpieceOpen] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);
  const dirtyRef = useRef(false);
  const pendingDialogRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const jumpRequestIdRef = useRef(0);
  const savingRef = useRef(false);
  const saveSequenceRef = useRef(0);
  const toastIdRef = useRef(0);
  const actionRef = useRef<(action: "ok" | "clear" | "borderline" | "ng" | "pending") => void>();
  const undoRef = useRef<() => void>();

  const showToast = useCallback((
    message: string,
    options: { tone?: TriageToastTone; action?: "pending" } = {}
  ) => {
    if (toastsMuted) return;
    const nextToast: TriageToast = {
      id: ++toastIdRef.current,
      message,
      tone: options.tone ?? "success",
      action: options.action ?? null,
      exiting: false
    };
    setToasts((current) => [
      ...current.map((item) => ({ ...item, exiting: true })),
      nextToast
    ].slice(-3));
  }, [toastsMuted]);

  const currentSample = navigation?.current_sample ?? null;
  const hasUnsavedDraft = Boolean(triage && currentSample?.id === triage.sample_id && JSON.stringify(draft) !== JSON.stringify(draftFromTriage(triage)));
  dirtyRef.current = hasUnsavedDraft;
  const requestNavigation = useCallback((action: () => void) => {
    if (savingRef.current) return;
    if (dirtyRef.current) setPendingNavigation(() => action);
    else action();
  }, []);

  useEffect(() => {
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!dirtyRef.current && !savingRef.current) return;
      event.preventDefault(); event.returnValue = "";
    }
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, []);

  useEffect(() => {
    if (!pendingNavigation) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = pendingDialogRef.current;
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !savingRef.current) { event.preventDefault(); setPendingNavigation(null); }
      if (event.key !== "Tab") return;
      const buttons = Array.from(dialog?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
      const first = buttons[0]; const last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); previousFocus?.focus(); };
  }, [pendingNavigation]);
  const activeDefectTypes = useMemo(
    () => defectTypes.filter((item) => item.is_active),
    [defectTypes]
  );
  const rootDefectTypes = useMemo(
    () => activeDefectTypes.filter((item) => item.parent_id === null),
    [activeDefectTypes]
  );
  const splitOk = policy?.split_ok ?? false;
  const currentResult = resultPresentation(triage, splitOk);
  const currentResultStyles = RESULT_STYLES[currentResult.tone];
  const lightCanvas = canvasTone === "light";
  const ngGrouping = policy?.ng_grouping ?? "none";
  const ngUsesDefectType = ngGrouping === "defect_type" || ngGrouping === "defect_type_and_severity";
  const ngUsesSeverity = ngGrouping === "severity" || ngGrouping === "defect_type_and_severity";
  const showDefectTypes =
    (draft.status === "ng" && ngUsesDefectType)
    || (draft.status === "ok" && splitOk && draft.okGrade === "borderline");
  const showDefectSeverity =
    (draft.status === "ng" && ngUsesSeverity)
    || (draft.status === "ok" && splitOk && draft.okGrade === "borderline");
  const progressDone = stats
    ? (stats.by_status.ok ?? 0) + (stats.by_status.ng ?? 0) + (stats.by_status.pending ?? 0)
    : 0;
  const pendingCount = stats?.by_status.pending ?? 0;
  const hasActiveTriageFilters = Boolean(
    filterStatus || filterOkGrade || filterDefectTypeId || filterSeverity
  );
  const currentSplitValue = queueScope === "current_split"
    ? queueSplit
    : currentSample ? currentSample.split ?? "unassigned" : undefined;
  const currentSplitQueueLabel = currentSplitValue
    ? `当前图划分：${currentSplitValue === "unassigned" ? "未指定" : currentSplitValue}`
    : "当前图划分";
  const firstRun = Boolean(
    policy
    && stats
    && !policy.onboarding_completed
    && stats.total_images > 0
    && stats.total_images === (stats.by_status.untriaged ?? 0)
  );

  const replaceSearchParams = useCallback((values: {
    sample?: number | null;
    queue?: TriageQueueScope;
    split?: string | null;
  }) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (values.sample) {
        next.set("sample", String(values.sample));
      } else if (values.sample === null) {
        next.delete("sample");
      }
      if (values.queue) {
        next.set("queue", values.queue);
      }
      if (values.split) {
        next.set("split", values.split);
      } else if (values.split === null) {
        next.delete("split");
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  useEffect(() => {
    if (!Number.isInteger(datasetId) || datasetId <= 0) {
      setError("数据集编号无效。");
      setLoading(false);
      return;
    }
    let cancelled = false;
    Promise.all([
      getDataset(datasetId),
      getTriagePolicy(datasetId),
      getTriageStats(datasetId),
      listDefectTypes(datasetId)
    ])
      .then(async ([datasetValue, policyValue, statsValue, defectTypeValues]) => {
        if (cancelled) return;
        if (!reviewRun) {
          const remembered = readTriageWork(datasetId, datasetValue.created_at);
          const restore = remembered && (!requestedSampleId || remembered.sampleIds.includes(requestedSampleId)) &&
            (!searchParams.toString() || searchParams.get("resume") === "1" || remembered.query === workQuery(searchParams));
          if (restore) {
            const checked = reconcileWork(remembered, (await getWorkState(datasetId, remembered.sampleIds)).items);
            if (cancelled) return;
            if (requestedSampleId && checked.work.sampleIds.includes(requestedSampleId) && !workIds(checked.work).includes(requestedSampleId)) checked.work.view = "all";
            setWork(checked.work);
            setMode(checked.work.mode);
            const restored = new URLSearchParams(checked.work.query);
            const currentId = requestedSampleId ?? checked.work.currentId;
            if (currentId) restored.set("sample", String(currentId));
            setSearchParams(restored, { replace: true });
            setWorkNotice(`已恢复上次工作范围。${checked.changed ? ` ${checked.changed} 张已变化，重新列入待处理。` : ""}${checked.removed ? ` ${checked.removed} 条记录已移除。` : ""}`);
          }
        }
        setDataset(datasetValue);
        setPolicy(policyValue);
        setPolicyDraft({
          split_ok: policyValue.split_ok,
          ng_grouping: policyValue.ng_grouping,
          instructions: policyValue.instructions,
          clear_ok_definition: policyValue.clear_ok_definition,
          borderline_ok_definition: policyValue.borderline_ok_definition,
          mild_definition: policyValue.mild_definition,
          moderate_definition: policyValue.moderate_definition,
          severe_definition: policyValue.severe_definition
        });
        setStats(statsValue);
        setDefectTypes(defectTypeValues);
        setWorkReady(true);
      })
      .catch((loadError) => {
        if (!cancelled) setError(errorMessage(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  function scopeRequest(query = scopeQuery): WorkScopeQuery {
    const params = new URLSearchParams(query);
    return { queue_scope: params.get("queue") as TriageQueueScope, sample_id: requestedSampleId ?? undefined,
      search: params.get("q") || undefined, split: params.get("split") || undefined,
      triage_status: params.get("status") || undefined, ok_grade: splitOk ? params.get("okGrade") || undefined : undefined,
      defect_severity: ngUsesSeverity ? params.get("severity") || undefined : undefined,
      defect_type_id: ngUsesDefectType ? Number(params.get("defectType")) || undefined : undefined };
  }

  useEffect(() => {
    if (!workReady || !dataset || reviewRun || activeWork) return;
    let cancelled = false;
    setLoading(true);
    getWorkScope(datasetId, scopeRequest()).then(scope => {
      if (cancelled) return;
      setWork({ version: 1, datasetId, datasetCreatedAt: dataset.created_at, query: scopeQuery, sampleIds: scope.sample_ids,
        completed: {}, skipped: [], currentId: requestedSampleId, view: "todo", mode });
      setNewWorkIds([]);
    }).catch(e => { if (!cancelled) { setError(errorMessage(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, [workReady, dataset, reviewRun, scopeQuery, Boolean(activeWork), navigationRevision]);

  function changeMode(value: "quick" | "detail") {
    setMode(value);
    setWork(current => current ? { ...current, mode: value } : current);
  }

  async function checkWork() {
    if (!activeWork || checkingWork) return;
    setCheckingWork(true);
    savingRef.current = true;
    try {
      const [state, scope] = await Promise.all([getWorkState(datasetId, activeWork.sampleIds), getWorkScope(datasetId, scopeRequest())]);
      const checked = reconcileWork(activeWork, state.items);
      setWork(checked.work);
      const known = new Set(activeWork.sampleIds);
      setNewWorkIds(scope.sample_ids.filter(id => !known.has(id)));
      setWorkNotice(`范围检查完成：${checked.changed} 张完成记录已变化，${checked.removed} 条记录已移除。`);
      setNavigationRevision(value => value + 1);
    } catch (e) { setError(errorMessage(e)); }
    finally { savingRef.current = false; setCheckingWork(false); }
  }

  function changeWorkView(view: WorkView) {
    requestNavigation(() => {
      setWork(value => value ? { ...value, view, currentId: null } : value);
      replaceSearchParams({ sample: null });
    });
  }

  function skipCurrent() {
    if (!activeWork || !currentSample || loading || saving || activeWork.view === "skipped" || activeWork.completed[currentSample.id] || activeWork.skipped.includes(currentSample.id)) return;
    requestNavigation(() => {
      const next = activeWorkIds?.find((id, index, ids) => index > ids.indexOf(currentSample.id)) ?? null;
      setWork(value => value ? { ...value, skipped: [...new Set([...value.skipped, currentSample.id])], currentId: next } : value);
      replaceSearchParams({ sample: next });
    });
  }

  useEffect(() => {
    if (firstRun) {
      setPolicyPanelOpen(true);
    }
  }, [firstRun]);

  useEffect(() => {
    setUndoStack([]);
    setToasts([]);
    setToastsMuted(false);
  }, [datasetId]);

  useEffect(() => {
    const exitingIds = toasts.filter((item) => item.exiting).map((item) => item.id);
    if (exitingIds.length === 0) return;
    const timeout = window.setTimeout(() => {
      setToasts((current) => current.filter((item) => !exitingIds.includes(item.id)));
    }, 420);
    return () => window.clearTimeout(timeout);
  }, [toasts]);

  useEffect(() => {
    if (error) setToasts([]);
  }, [error]);

  useEffect(() => {
    if (!dataset) return;
    try {
      const stored = window.localStorage.getItem(canvasToneStorageKey(dataset));
      setCanvasTone(stored === "light" ? "light" : "dark");
    } catch {
      setCanvasTone("dark");
    }
  }, [dataset]);

  useEffect(() => {
    if (navigation?.current_index === null || navigation?.current_index === undefined) {
      setPositionDraft(null);
      setPositionInput("");
      return;
    }
    const position = navigation.current_index + 1;
    setPositionDraft(position);
    setPositionInput(String(position));
  }, [navigation?.current_index, navigation?.total]);

  useEffect(() => {
    if (!Number.isInteger(datasetId) || datasetId <= 0) return;
    if (!policy || !workReady || (!reviewRun && !activeWork)) return;
    jumpRequestIdRef.current += 1;
    setJumping(false);
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    const request = activeWork ? getWorkNavigation(datasetId, activeWorkIds ?? [], navigationSampleId ?? activeWork.currentId) : getTriageNavigation({
      datasetId,
      reviewRun,
      sampleId: navigationSampleId,
      queueScope,
      split: queueSplit,
      triageStatus: filterStatus,
      okGrade: splitOk ? filterOkGrade : undefined,
      defectSeverity: ngUsesSeverity ? filterSeverity : undefined,
      defectTypeId: ngUsesDefectType ? filterDefectTypeId : undefined
    });
    request
      .then(async (navigationValue) => {
        if (requestId !== requestIdRef.current) return;
        setNavigation(navigationValue);
        const sample = navigationValue.current_sample;
        if (!sample) {
          if (requestedSampleId) replaceSearchParams({ sample: null });
          setTriage(null);
          setDraft(blankDraft());
          setImageReady(false);
          return;
        }
        if (sample.id !== requestedSampleId) {
          replaceSearchParams({ sample: sample.id });
        }
        const triageValue = await getSampleTriage(sample.id);
        if (requestId !== requestIdRef.current) return;
        setTriage(triageValue);
        setDraft(draftFromTriage(triageValue));
        setZoom(1);
        setImageReady(false);
        setWork(value => value && value.currentId !== sample.id ? { ...value, currentId: sample.id } : value);
      })
      .catch((loadError) => {
        if (requestId === requestIdRef.current) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });
  }, [
    datasetId,
    filterDefectTypeId,
    filterOkGrade,
    filterSeverity,
    filterStatus,
    navigationSampleId,
    navigationRevision,
    ngUsesDefectType,
    ngUsesSeverity,
    policy,
    queueScope,
    queueSplit,
    replaceSearchParams,
    requestedSampleId,
    splitOk,
    reviewRun,
    workReady,
    Boolean(activeWork),
    activeIdsKey
  ]);

  useEffect(() => {
    if (!policy) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      let changed = false;
      if (!splitOk && next.has("okGrade")) {
        next.delete("okGrade");
        changed = true;
      }
      if (!ngUsesDefectType && next.has("defectType")) {
        next.delete("defectType");
        changed = true;
      }
      if (!ngUsesSeverity && next.has("severity")) {
        next.delete("severity");
        changed = true;
      }
      return changed ? next : current;
    }, { replace: true });
  }, [ngUsesDefectType, ngUsesSeverity, policy, setSearchParams, splitOk]);

  useEffect(() => {
    const nextSample = navigation?.next_sample;
    if (!nextSample) return;
    const image = new Image();
    image.src = getSampleFileUrl(nextSample.id);
  }, [navigation?.next_sample]);

  const advanceAfterSave = useCallback((nextSampleId: number | null) => {
    replaceSearchParams({ sample: nextSampleId });
  }, [replaceSearchParams]);

  const savePayload = useCallback(async (
    payload: Omit<SampleTriageWrite, "expected_version" | "expected_file_hash">,
    options: { advance: boolean; message: string; pendingGuidance?: boolean }
  ) => {
    if (!currentSample || !triage || savingRef.current) return false;
    savingRef.current = true;
    const saveSequence = ++saveSequenceRef.current;
    const nextSampleId = navigation?.next_sample?.id ?? null;
    const before = triage;
    setSaving(true);
    setError(null);
    try {
      let saved: SampleTriage;
      try {
        saved = await replaceSampleTriage(currentSample.id, {
          ...payload, expected_version: triage.triage_version, expected_file_hash: triage.file_hash
        });
      } catch (writeError) {
        if (!axios.isAxiosError(writeError) || writeError.response && writeError.response.status < 500) throw writeError;
        const actual = await getSampleTriage(currentSample.id);
        const expectedDefects = [...(payload.defect_type_ids ?? [])].sort((a, b) => a - b);
        const actualDefects = actual.defect_types.map(d => d.id).sort((a, b) => a - b);
        const matches = (actual.triage_version === before.triage_version + 1 || actual.triage_version === before.triage_version) &&
          actual.file_hash === before.file_hash && !actual.outdated &&
          actual.current_policy_version === before.current_policy_version &&
          actual.triage_status === payload.triage_status && actual.ok_grade === (payload.ok_grade ?? null) &&
          actual.defect_severity === (payload.defect_severity ?? null) &&
          actual.primary_defect_type_id === (payload.primary_defect_type_id ?? null) &&
          actual.triage_note === (payload.triage_note?.trim() || null) &&
          JSON.stringify(actualDefects) === JSON.stringify(expectedDefects);
        if (!matches) throw writeError;
        saved = actual;
      }
      if (saved.triage_version > before.triage_version) {
        setUndoStack((current) => [
          ...current,
          { sample: currentSample, before, savedVersion: saved.triage_version }
        ].slice(-20));
      }
      setTriage(saved);
      setDraft(draftFromTriage(saved));
      if (workRef.current?.sampleIds.includes(currentSample.id) && !reviewRun) {
        const nextWork = completeWorkSample(workRef.current, { sample_id: currentSample.id, triage_version: saved.triage_version,
          file_hash: saved.file_hash, triage_policy_version: saved.triage_policy_version, triage_status: saved.triage_status, triage_outdated: saved.outdated });
        setWork({ ...nextWork, currentId: options.advance ? nextSampleId : currentSample.id });
      }
      if (reviewRun && saved.triage_status !== "pending") {
        await updateValidationReview(reviewRun,currentSample.id,{state:"reviewed",expected_version:saved.triage_version,expected_file_hash:saved.file_hash});
        setNavigationRevision(value=>value+1);
      }
      showToast(options.message, {
        action: options.pendingGuidance ? "pending" : undefined
      });
      if (options.advance) {
        advanceAfterSave(nextSampleId);
      }
      void getTriageStats(datasetId).then((nextStats) => {
        if (saveSequence !== saveSequenceRef.current) return;
        setStats(nextStats);
      }).catch(() => undefined);
      return true;
    } catch (saveError) {
      setError(errorMessage(saveError));
      return false;
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [advanceAfterSave, currentSample, datasetId, navigation?.next_sample?.id, showToast, triage, reviewRun]);

  const quickAction = useCallback((action: "ok" | "clear" | "borderline" | "ng" | "pending") => {
    const common = {
      defect_type_ids: [] as number[],
      primary_defect_type_id: null,
      triage_note: null,
      defect_severity: null
    };
    if (action === "ok") {
      void savePayload(
        { ...common, triage_status: "ok", ok_grade: null },
        { advance: true, message: "已保存为 OK" }
      );
    } else if (action === "clear") {
      void savePayload(
        { ...common, triage_status: "ok", ok_grade: "clear" },
        { advance: true, message: `已保存为${okGradeCopy.clear}` }
      );
    } else if (action === "borderline") {
      void savePayload(
        { ...common, triage_status: "ok", ok_grade: "borderline" },
        { advance: true, message: `已保存为${okGradeCopy.borderline}` }
      );
    } else if (action === "ng") {
      void savePayload(
        { ...common, triage_status: "ng", ok_grade: null },
        { advance: true, message: "已保存为 NG" }
      );
    } else {
      void savePayload(
        { ...common, triage_status: "pending", ok_grade: null },
        { advance: true, message: "已加入待定复看", pendingGuidance: true }
      );
    }
  }, [savePayload]);
  actionRef.current = quickAction;

  const saveDetail = useCallback((advance = true) => {
    let nextDraft = draft;
    if (draft.status === "untriaged") {
      if (draft.note.trim()) {
        setError("备注尚未保存，请先选择 OK、NG 或待定判定。");
        return Promise.resolve(false);
      }
      nextDraft = blankDraft();
    } else if (draft.status === "ok" && !splitOk) {
      nextDraft = {
        ...draft,
        okGrade: null,
        severity: null,
        defectTypeIds: [],
        primaryDefectTypeId: null
      };
    } else if (draft.status === "ok" && draft.okGrade === "clear") {
      nextDraft = { ...draft, severity: null, defectTypeIds: [], primaryDefectTypeId: null };
    } else if (draft.status === "ng") {
      nextDraft = {
        ...draft,
        okGrade: null,
        severity: ngUsesSeverity ? draft.severity : null,
        defectTypeIds: ngUsesDefectType ? draft.defectTypeIds : [],
        primaryDefectTypeId: ngUsesDefectType ? draft.primaryDefectTypeId : null
      };
    } else if (draft.status === "pending") {
      nextDraft = {
        ...draft,
        okGrade: null,
        severity: null,
        defectTypeIds: [],
        primaryDefectTypeId: null
      };
    }
    if (nextDraft.status === "ok" && splitOk && !nextDraft.okGrade) {
      setError(`请选择${okGradeCopy.clear}或${okGradeCopy.borderline}。`);
      return Promise.resolve(false);
    }
    return savePayload(
      {
        triage_status: nextDraft.status,
        ok_grade: nextDraft.status === "ok" ? nextDraft.okGrade : null,
        defect_severity: nextDraft.severity,
        defect_type_ids: nextDraft.defectTypeIds,
        primary_defect_type_id: nextDraft.primaryDefectTypeId,
        triage_note: nextDraft.note.trim() || null
      },
      {
        advance,
        message: nextDraft.status === "pending"
          ? "已加入待定复看"
          : "分拣结果已保存",
        pendingGuidance: nextDraft.status === "pending"
      }
    );
  }, [draft, ngUsesDefectType, ngUsesSeverity, savePayload, splitOk]);

  const undoLast = useCallback(async () => {
    const undoRecord = undoStack[undoStack.length - 1];
    if (!undoRecord || savingRef.current) return;
    savingRef.current = true;
    saveSequenceRef.current += 1;
    setSaving(true);
    setError(null);
    try {
      const reverted = await replaceSampleTriage(
        undoRecord.sample.id,
        writeFromTriage(undoRecord.before, undoRecord.savedVersion)
      );
      if (reviewRun) await updateValidationReview(reviewRun,undoRecord.sample.id,{state:"pending"});
      setWork(value => {
        if (!value) return value;
        const completed = { ...value.completed };
        delete completed[undoRecord.sample.id];
        return { ...value, completed, skipped: value.skipped.filter(id => id !== undoRecord.sample.id), currentId: undoRecord.sample.id, view: "todo" };
      });
      setUndoStack((current) => {
        const next = current.slice(0, -1);
        const previousIndex = next.map((item) => item.sample.id).lastIndexOf(
          undoRecord.sample.id
        );
        if (previousIndex >= 0) {
          next[previousIndex] = {
            ...next[previousIndex],
            savedVersion: reverted.triage_version
          };
        }
        return next;
      });
      if (currentSample?.id === undoRecord.sample.id) {
        setTriage(reverted);
        setDraft(draftFromTriage(reverted));
      }
      showToast(
        undoStack.length > 1 ? `已撤销上一步 · 还可撤销 ${undoStack.length - 1} 步` : "已撤销上一步",
        { tone: "info" }
      );
      setStats(await getTriageStats(datasetId));
      replaceSearchParams({ sample: undoRecord.sample.id });
      setNavigationRevision((current) => current + 1);
    } catch (undoError) {
      setError(`无法撤销 ${undoRecord.sample.filename}：${errorMessage(undoError)} 当前数据未被覆盖。`);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [currentSample?.id, datasetId, replaceSearchParams, showToast, undoStack, reviewRun]);
  undoRef.current = () => requestNavigation(() => void undoLast());

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.isComposing || isTypingTarget(event.target) || referenceOpen || workpieceOpen || pendingNavigation || policyPanelOpen) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undoRef.current?.();
        return;
      }
      if (savingRef.current || loading || !imageReady || mode !== "quick") return;
      const actions = actionRef.current;
      if (splitOk) {
        if (event.key === "1") actions?.("clear");
        else if (event.key === "2") actions?.("borderline");
        else if (event.key === "3") actions?.("ng");
        else if (event.key === "4") actions?.("pending");
        else if (event.key !== " ") return;
      } else {
        if (event.key === "1") actions?.("ok");
        else if (event.key === "2") actions?.("ng");
        else if (event.key === "3") actions?.("pending");
        else if (event.key !== " ") return;
      }
      if (event.key === " " && activeWork) {
        event.preventDefault();
        skipCurrent();
      } else if (event.key === " " && navigation?.next_sample) {
        event.preventDefault();
        requestNavigation(() => replaceSearchParams({ sample: navigation.next_sample?.id ?? null }));
      } else if (event.key === " ") {
        return;
      }
      event.preventDefault();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [imageReady, loading, mode, navigation?.next_sample, replaceSearchParams, splitOk, referenceOpen, workpieceOpen, pendingNavigation, policyPanelOpen, requestNavigation, activeWork]);

  function toggleDefectType(id: number) {
    setDraft((current) => {
      const selected = current.defectTypeIds.includes(id);
      const defectTypeIds = selected
        ? current.defectTypeIds.filter((item) => item !== id)
        : [...current.defectTypeIds, id];
      return {
        ...current,
        defectTypeIds,
        primaryDefectTypeId: selected && current.primaryDefectTypeId === id
          ? defectTypeIds[0] ?? null
          : current.primaryDefectTypeId ?? id
      };
    });
  }

  async function addDefectType() {
    const name = newDefectName.trim();
    if (!name || creatingDefect) return;
    setCreatingDefect(true);
    setError(null);
    try {
      const created = await createDefectType(datasetId, {
        name,
        parent_id: newDefectParent
      });
      setDefectTypes((current) => [...current, created]);
      setDraft((current) => ({
        ...current,
        defectTypeIds: [...current.defectTypeIds, created.id],
        primaryDefectTypeId: current.primaryDefectTypeId ?? created.id
      }));
      setNewDefectName("");
      setNewDefectParent(null);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setCreatingDefect(false);
    }
  }

  function setTriageFilter(name: string, value: string) {
    requestNavigation(() => {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(name, value);
        else next.delete(name);
        next.delete("sample");
        return next;
      }, { replace: true });
    });
  }

  function clearTriageFilters() {
    requestNavigation(() => {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        ["status", "okGrade", "defectType", "severity", "sample"].forEach((key) => next.delete(key));
        return next;
      }, { replace: true });
    });
  }

  function selectQueue(nextQueue: TriageQueueScope) {
    requestNavigation(() => {
      replaceSearchParams({
        queue: nextQueue,
        sample: null,
        split: nextQueue === "current_split"
          ? currentSample?.split ?? queueSplit ?? "unassigned"
          : null
      });
    });
  }

  function toggleCanvasTone() {
    const nextTone: CanvasTone = lightCanvas ? "dark" : "light";
    setCanvasTone(nextTone);
    if (!dataset) return;
    try {
      window.localStorage.setItem(canvasToneStorageKey(dataset), nextTone);
    } catch {
      // 浏览器禁用本地存储时仍允许本次页面切换。
    }
  }

  function queueCount(scope: TriageQueueScope): number | null {
    if (!stats) return null;
    if (scope === "untriaged") return stats.by_status.untriaged ?? 0;
    if (scope === "pending") return pendingCount;
    if (scope === "current_filter") return stats.total_images;
    return queueScope === "current_split" ? navigation?.total ?? 0 : null;
  }

  async function jumpToPosition(position: number) {
    const total = navigation?.total ?? 0;
    if (!Number.isInteger(position) || position < 1 || position > total) {
      setError(`请输入 1 至 ${total} 之间的图片位置。`);
      return;
    }
    setPositionDraft(position);
    setPositionInput(String(position));
    if (navigation?.current_index === position - 1 || jumping) return;
    const jumpRequestId = ++jumpRequestIdRef.current;
    setJumping(true);
    setError(null);
    try {
      const target = activeWork ? await getWorkNavigation(datasetId, activeWorkIds ?? [], undefined, position) : await getTriageNavigation({
        datasetId,
        reviewRun,
        targetIndex: position,
        queueScope,
        split: queueSplit,
        triageStatus: filterStatus,
        okGrade: splitOk ? filterOkGrade : undefined,
        defectSeverity: ngUsesSeverity ? filterSeverity : undefined,
        defectTypeId: ngUsesDefectType ? filterDefectTypeId : undefined
      });
      if (jumpRequestId !== jumpRequestIdRef.current) return;
      if (!target.current_sample) {
        setError("目标图片已不在当前队列，请刷新后重试。");
        return;
      }
      requestNavigation(() => replaceSearchParams({ sample: target.current_sample?.id ?? null }));
    } catch (jumpError) {
      if (jumpRequestId === jumpRequestIdRef.current) {
        setError(errorMessage(jumpError));
      }
    } finally {
      if (jumpRequestId === jumpRequestIdRef.current) {
        setJumping(false);
      }
    }
  }

  function openPolicyModal() {
    if (!policy) return;
    requestNavigation(() => {
      setPolicyDraft({
        split_ok: policy.split_ok,
        ng_grouping: policy.ng_grouping,
        instructions: policy.instructions,
        clear_ok_definition: policy.clear_ok_definition,
        borderline_ok_definition: policy.borderline_ok_definition,
        mild_definition: policy.mild_definition,
        moderate_definition: policy.moderate_definition,
        severe_definition: policy.severe_definition
      });
      setPolicyImpact(null);
      setPolicyPanelOpen(true);
    });
  }

  function closePolicyModal() {
    if (firstRun) return;
    setPolicyImpact(null);
    setPolicyPanelOpen(false);
  }

  async function commitPolicy() {
    if (!policyDraft || !policy) return;
    const reviewCount = policyImpact?.requires_review_count ?? 0;
    const saved = await updateTriagePolicy(datasetId, {
      ...policyDraft,
      expected_version: policy.version,
      complete_onboarding: true
    });
    setPolicy(saved);
    setPolicyDraft({
      split_ok: saved.split_ok,
      ng_grouping: saved.ng_grouping,
      instructions: saved.instructions,
      clear_ok_definition: saved.clear_ok_definition,
      borderline_ok_definition: saved.borderline_ok_definition,
      mild_definition: saved.mild_definition,
      moderate_definition: saved.moderate_definition,
      severe_definition: saved.severe_definition
    });
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (!saved.split_ok) next.delete("okGrade");
      if (saved.ng_grouping !== "defect_type" && saved.ng_grouping !== "defect_type_and_severity") {
        next.delete("defectType");
      }
      if (saved.ng_grouping !== "severity" && saved.ng_grouping !== "defect_type_and_severity") {
        next.delete("severity");
      }
      return next;
    }, { replace: true });
    const statsValue = await getTriageStats(datasetId);
    setStats(statsValue);
    if (currentSample) {
      const triageValue = await getSampleTriage(currentSample.id);
      setTriage(triageValue);
      setDraft(draftFromTriage(triageValue));
    }
    showToast(
      reviewCount > 0 ? `规则已更新 · ${reviewCount} 张待复核` : "分拣规则已保存",
      { tone: "info" }
    );
    setUndoStack([]);
    setPolicyImpact(null);
    setPolicyPanelOpen(false);
  }

  async function savePolicy() {
    if (!policyDraft || !policy || policySaving) return;
    setPolicySaving(true);
    setError(null);
    try {
      if (policyImpact?.changed && policyImpact.requires_review_count > 0) {
        await commitPolicy();
      } else {
        const impact = await previewTriagePolicy(datasetId, {
          ...policyDraft,
          expected_version: policy.version
        });
        if (impact.changed && impact.requires_review_count > 0) {
          setPolicyImpact(impact);
          return;
        }
        await commitPolicy();
      }
    } catch (saveError) {
      setError(errorMessage(saveError));
      setPolicyImpact(null);
    } finally {
      setPolicySaving(false);
    }
  }

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="flex min-w-0 items-center gap-4">
            <Link
              state={location.state}
              to={reviewRun ? `/datasets/${datasetId}/validate/${reviewRun}${reviewReturn.startsWith("?")?reviewReturn:""}` : `/datasets/${datasetId}`}
              onClick={(event) => {
                if (!hasUnsavedDraft && !saving) return;
                event.preventDefault();
                requestNavigation(() => navigate(reviewRun ? `/datasets/${datasetId}/validate/${reviewRun}${reviewReturn.startsWith("?") ? reviewReturn : ""}` : `/datasets/${datasetId}`, { state: location.state }));
              }}
              className="inline-flex min-h-11 shrink-0 items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-950"
            >
              <ArrowLeft size={18} /> {reviewRun?"返回本次实验":"返回数据集"}
            </Link>
            <div className="hidden h-7 w-px bg-line sm:block" />
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold">{reviewRun?"实验候选复核":"快速分拣"} · {dataset?.name ?? "加载中"}</h1>
              <p className="text-xs text-gray-500">规则版本 {policy?.version ?? "-"} · 保存成功后自动进入下一张</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" disabled={loading || saving || !currentSample} onClick={() => setWorkpieceOpen(true)} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">工件多视角</button>
            <button type="button" disabled={loading || saving || !dataset} onClick={() => setReferenceOpen(true)} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40"><BookOpen size={16} />参考卡</button>
            <button
              type="button"
              onClick={openPolicyModal}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Settings2 size={16} /> 分拣层级
            </button>
            <button
              type="button"
              title="撤销上一步（Ctrl+Z）"
              onClick={() => requestNavigation(() => void undoLast())}
              disabled={undoStack.length === 0 || saving}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RotateCcw size={16} /> 撤销 {undoStack.length}/20
            </button>
          </div>
        </div>
        <nav
          aria-label="分拣队列"
          className="mx-auto flex max-w-[1600px] gap-1 overflow-x-auto px-5 pb-3"
        >
          {(reviewRun?[]:QUEUE_OPTIONS).map((scope) => {
            const count = queueCount(scope);
            const active = queueScope === scope;
            const pending = scope === "pending" && pendingCount > 0;
            return (
              <button
                key={scope}
                type="button"
                aria-pressed={active}
                onClick={() => selectQueue(scope)}
                className={`inline-flex min-h-10 shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors ${
                  active
                    ? "border-gray-900 bg-gray-900 text-white"
                    : pending
                      ? "border-violet-300 bg-violet-50 text-violet-800 hover:bg-violet-100"
                      : "border-line bg-white text-gray-700 hover:bg-gray-50"
                }`}
              >
                {scope === "current_split" ? currentSplitQueueLabel : QUEUE_LABELS[scope]}
                {count !== null && (
                  <span className={`rounded-full px-2 py-0.5 text-xs ${active ? "bg-white/15 text-white" : "bg-gray-100 text-gray-600"}`}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </header>

      <TriagePolicyModal
        open={policyPanelOpen}
        firstRun={firstRun}
        draft={policyDraft}
        stats={stats}
        impact={policyImpact}
        saving={policySaving}
        onChange={(value) => {
          setPolicyDraft(value);
          setPolicyImpact(null);
        }}
        onCancel={closePolicyModal}
        onSubmit={() => void savePolicy()}
      />

      {referenceOpen && <ReferenceCasesPanel datasetId={datasetId} currentSample={currentSample} onClose={() => setReferenceOpen(false)} />}
      {workpieceOpen && currentSample && <WorkpieceViewsPanel sampleId={currentSample.id} onClose={() => setWorkpieceOpen(false)} />}
      <div ref={pendingDialogRef}><Modal open={Boolean(pendingNavigation)} title="本张有未保存的分拣修改" onClose={() => { if (!saving) setPendingNavigation(null); }} dismissible={!saving}>
        <div className="p-5"><p className="text-sm text-gray-600">保存当前判定后继续，或放弃本次修改。保存失败时会留在当前图片。</p>{error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}<div className="mt-4 flex flex-wrap gap-2">
          <button type="button" disabled={saving || !imageReady} onClick={() => void saveDetail(false).then((saved) => { if (saved && pendingNavigation) { const action = pendingNavigation; setPendingNavigation(null); action(); } })} className="min-h-10 rounded-lg bg-gray-900 px-3 text-sm text-white disabled:opacity-40">{saving ? "正在保存…" : "保存并继续"}</button>
          <button type="button" disabled={saving} onClick={() => { const action = pendingNavigation; if (triage) setDraft(draftFromTriage(triage)); dirtyRef.current = false; setPendingNavigation(null); action?.(); }} className="min-h-10 rounded-lg border border-line px-3 text-sm disabled:opacity-40">放弃修改</button>
          <button type="button" disabled={saving} onClick={() => setPendingNavigation(null)} className="min-h-10 rounded-lg border border-line px-3 text-sm disabled:opacity-40">取消</button>
        </div></div>
      </Modal></div>

      <section className="mx-auto max-w-[1600px] px-5 py-4">
        {activeWork && <section aria-label="本次分拣工作" className="mb-4 space-y-3 rounded-xl border border-line bg-white p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0"><h2 className="font-semibold">本次分拣工作 · 固定 {activeWork.sampleIds.length} 张</h2>
              <p className="mt-1 text-sm text-gray-600">已处理 {Object.keys(activeWork.completed).length} · 其中待确认 {Object.values(activeWork.completed).filter(item => item.triage_status === "pending").length} · 暂时跳过 {activeWork.skipped.length} · 待处理 {activeWork.sampleIds.length - Object.keys(activeWork.completed).length - activeWork.skipped.length}</p>
              <p className="mt-1 text-xs text-gray-500">范围按相对路径排序；切换队列或筛选会开始该范围的新工作。进度保存在当前浏览器，未保存草稿和撤销历史不跨会话保留。</p>
            </div>
            <button type="button" disabled={checkingWork || loading || saving} onClick={() => requestNavigation(() => void checkWork())} className="min-h-10 rounded-lg border border-line px-3 text-sm disabled:opacity-40">{checkingWork ? "正在检查…" : "检查新增与变化"}</button>
          </div>
          <div className="flex flex-wrap gap-2">
            {([["todo", "继续待处理"], ["skipped", "回看跳过"], ["all", "回看本次全部"]] as const).map(([view, label]) => <button key={view} type="button" disabled={saving || loading} aria-pressed={activeWork.view === view} onClick={() => changeWorkView(view)} className={`min-h-10 rounded-lg border px-3 text-sm disabled:opacity-40 ${activeWork.view === view ? "border-gray-900 bg-gray-900 text-white" : "border-line"}`}>{label}</button>)}
            <button type="button" disabled={!currentSample || loading || saving || Boolean(currentSample && activeWork.completed[currentSample.id]) || activeWork.view === "skipped"} onClick={skipCurrent} className="min-h-10 rounded-lg border border-line px-3 text-sm disabled:opacity-40">暂时跳过（空格）</button>
            {activeWork.view === "skipped" && currentSample && <button type="button" disabled={saving || loading} onClick={() => requestNavigation(() => { setWork(value => value ? { ...value, skipped: value.skipped.filter(id => id !== currentSample.id), view: "todo", currentId: currentSample.id } : value); })} className="min-h-10 rounded-lg border border-line px-3 text-sm disabled:opacity-40">放回待处理</button>}
          </div>
          {workNotice && <p role="status" className="text-xs text-gray-600">{workNotice}</p>}
          {storageWarning && <p role="alert" className="text-sm text-amber-800">浏览器无法保存工作进度，本页仍可操作；关闭页面后可能无法续接。</p>}
          {newWorkIds.length > 0 && <div className="flex flex-wrap items-center gap-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><span>当前条件另有 {newWorkIds.length} 张图片未纳入本次。</span><button type="button" disabled={saving || loading || activeWork.sampleIds.length + newWorkIds.length > 10000} onClick={() => requestNavigation(() => { setWork(value => value ? { ...value, sampleIds: [...value.sampleIds, ...newWorkIds], view: "todo" } : value); setNewWorkIds([]); })} className="min-h-9 rounded border border-amber-300 px-3 disabled:opacity-40">确认纳入本次</button><span className="text-xs">单次最多 10000 张</span></div>}
        </section>}
        {reviewRun&&<p className="mb-4 rounded-lg border bg-white p-4 text-sm">本实验待复核 {navigation?.total??0} 张。保留原判定也可再次确认；保存有效 OK/NG 后移出候选，待定仍保留。历史实验不改写。</p>}
        {!reviewRun&&<div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded-xl border border-line bg-white px-4 py-3">
            <div className="text-xs text-gray-500">已处理 / 图片</div>
            <div className="mt-1 text-xl font-semibold">{progressDone} / {stats?.total_images ?? 0}</div>
          </div>
          {splitOk ? (
            <>
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                <div className="text-xs text-emerald-700">{okGradeCopy.clear}</div>
                <div className="mt-1 text-xl font-semibold text-emerald-900">{stats?.by_ok_grade.clear ?? 0}</div>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                <div className="text-xs text-amber-700">{okGradeCopy.borderline}</div>
                <div className="mt-1 text-xl font-semibold text-amber-900">{stats?.by_ok_grade.borderline ?? 0}</div>
              </div>
            </>
          ) : (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 lg:col-span-2">
              <div className="text-xs text-emerald-700">OK</div>
              <div className="mt-1 text-xl font-semibold text-emerald-900">{stats?.by_status.ok ?? 0}</div>
            </div>
          )}
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3">
            <div className="text-xs text-red-700">NG</div>
            <div className="mt-1 text-xl font-semibold text-red-900">{stats?.by_status.ng ?? 0}</div>
          </div>
          <div className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-3">
            <div className="text-xs text-violet-700">待定 / 已过期</div>
            <div className="mt-1 text-xl font-semibold text-violet-900">
              {stats?.by_status.pending ?? 0} / {stats?.outdated ?? 0}
            </div>
          </div>
        </div>}

        {error && (
          <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <CircleAlert size={18} className="mt-0.5 shrink-0" /> {error}
          </div>
        )}
        {!reviewRun && queueScope === "current_filter" && (
          <section className="mb-4 rounded-xl border border-line bg-white p-4 shadow-sm" aria-label="分拣统计筛选">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-40 flex-1">
                <label htmlFor="filter-status" className="text-xs font-medium text-gray-600">判定状态</label>
                <select id="filter-status" value={filterStatus ?? ""} onChange={(event) => setTriageFilter("status", event.target.value)} className="mt-1 min-h-10 w-full rounded-lg border border-line bg-white px-3 text-sm">
                  <option value="">全部状态</option>
                  {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </div>
              {splitOk && (
                <div className="min-w-40 flex-1">
                  <label htmlFor="filter-ok-grade" className="text-xs font-medium text-gray-600">OK 等级</label>
                  <select id="filter-ok-grade" value={filterOkGrade ?? ""} onChange={(event) => setTriageFilter("okGrade", event.target.value)} className="mt-1 min-h-10 w-full rounded-lg border border-line bg-white px-3 text-sm">
                    <option value="">全部 OK 等级</option>
                    <option value="clear">{okGradeCopy.clear}</option>
                    <option value="borderline">{okGradeCopy.borderline}</option>
                  </select>
                </div>
              )}
              {ngUsesDefectType && (
                <div className="min-w-40 flex-1">
                  <label htmlFor="filter-defect-type" className="text-xs font-medium text-gray-600">缺陷类别</label>
                  <select id="filter-defect-type" value={filterDefectTypeId ?? ""} onChange={(event) => setTriageFilter("defectType", event.target.value)} className="mt-1 min-h-10 w-full rounded-lg border border-line bg-white px-3 text-sm">
                    <option value="">全部缺陷类别</option>
                    {activeDefectTypes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </div>
              )}
              {ngUsesSeverity && (
                <div className="min-w-40 flex-1">
                  <label htmlFor="filter-severity" className="text-xs font-medium text-gray-600">缺陷程度</label>
                  <select id="filter-severity" value={filterSeverity ?? ""} onChange={(event) => setTriageFilter("severity", event.target.value)} className="mt-1 min-h-10 w-full rounded-lg border border-line bg-white px-3 text-sm">
                    <option value="">全部程度</option>
                    {Object.entries(SEVERITY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
              )}
              <button type="button" onClick={clearTriageFilters} className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50">清除筛选</button>
            </div>
          </section>
        )}

        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
          <section className={`relative flex h-[640px] min-w-0 flex-col overflow-hidden rounded-2xl border shadow-sm transition-colors duration-200 sm:h-[680px] xl:h-[clamp(620px,calc(100vh-190px),820px)] ${lightCanvas ? "border-gray-300 bg-white" : "border-line bg-gray-950"}`}>
            <div className={`flex min-h-12 items-center justify-between gap-3 border-b px-4 text-sm transition-colors duration-200 ${lightCanvas ? "border-gray-200 text-gray-700" : "border-white/10 text-gray-300"}`}>
              <div className="min-w-0 flex-1 truncate">
                {currentSample
                  ? currentSample.relative_path
                  : queueScope === "current_split" ? currentSplitQueueLabel : QUEUE_LABELS[queueScope]}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {currentSample && (
                  <span className={`rounded-full border px-3 py-1 text-sm font-bold shadow-sm ${currentResultStyles.badge}`}>
                    本张 · {currentResult.label}
                    {triage?.outdated ? " · 待复核" : ""}
                  </span>
                )}
                <button
                  type="button"
                  aria-label={lightCanvas ? "切换为黑色画布" : "切换为白色画布"}
                  title={lightCanvas ? "切换为黑色画布" : "切换为白色画布"}
                  onClick={toggleCanvasTone}
                  className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-semibold transition-colors ${lightCanvas ? "border-gray-300 bg-gray-50 text-gray-800 hover:bg-gray-100" : "border-white/20 bg-white/10 text-gray-100 hover:bg-white/15"}`}
                >
                  {lightCanvas ? <Sun size={16} /> : <Moon size={16} />}
                  <span className="hidden sm:inline">{lightCanvas ? "白色画布" : "黑色画布"}</span>
                </button>
              </div>
            </div>
            {currentSample && navigation && navigation.total > 1 && positionDraft !== null && (
              <div className={`flex flex-wrap items-center gap-3 border-b px-4 py-2.5 text-xs transition-colors duration-200 ${lightCanvas ? "border-gray-200 text-gray-600" : "border-white/10 text-gray-300"}`}>
                <label htmlFor="triage-position-slider" className="shrink-0 font-medium">
                  队列进度
                </label>
                <input
                  id="triage-position-slider"
                  aria-label="拖动跳转图片位置"
                  type="range"
                  min={1}
                  max={navigation.total}
                  value={positionDraft}
                  disabled={saving || jumping}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    setPositionDraft(value);
                    setPositionInput(String(value));
                  }}
                  onPointerUp={(event) => void jumpToPosition(Number(event.currentTarget.value))}
                  onKeyUp={(event) => {
                    if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
                      void jumpToPosition(Number(event.currentTarget.value));
                    }
                  }}
                  className={`h-2 min-w-40 flex-1 cursor-pointer disabled:cursor-wait ${lightCanvas ? "accent-gray-900" : "accent-white"}`}
                />
                <form
                  noValidate
                  className="flex items-center gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void jumpToPosition(Number(positionInput));
                  }}
                >
                  <input
                    aria-label="跳转位置"
                    type="number"
                    min={1}
                    max={navigation.total}
                    value={positionInput}
                    disabled={saving || jumping}
                    onChange={(event) => setPositionInput(event.target.value)}
                    className={`h-9 w-20 rounded-md border px-2 text-center text-sm outline-none ${lightCanvas ? "border-gray-300 bg-gray-50 text-gray-900 focus:border-gray-700" : "border-white/20 bg-white/10 text-white focus:border-white/60"}`}
                  />
                  <span className="text-gray-500">/ {navigation.total}</span>
                  <button
                    type="submit"
                    disabled={saving || jumping}
                    className={`h-9 rounded-md border px-3 font-medium disabled:opacity-40 ${lightCanvas ? "border-gray-300 text-gray-800 hover:bg-gray-100" : "border-white/20 text-gray-100 hover:bg-white/10"}`}
                  >
                    {jumping ? "跳转中…" : "跳转"}
                  </button>
                </form>
              </div>
            )}
            <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto p-5">
              {loading ? (
                <div className={`flex items-center gap-2 text-sm ${lightCanvas ? "text-gray-600" : "text-gray-300"}`}><Loader2 className="animate-spin" size={20} /> 加载图片…</div>
              ) : currentSample ? (
                <img
                  key={`${currentSample.id}-${currentSample.file_hash}`}
                  src={getSampleFileUrl(currentSample.id)}
                  alt={currentSample.filename}
                  draggable={false}
                  onLoad={() => {
                    setImageReady(true);
                    setError(null);
                  }}
                  onError={() => {
                    setImageReady(false);
                    setError("图片加载失败，当前判定已禁用。");
                  }}
                  style={{ transform: `scale(${zoom})` }}
                  className="max-h-full max-w-full select-none object-contain transition-transform"
                />
              ) : (
                <div className={`max-w-md text-center ${lightCanvas ? "text-gray-700" : "text-gray-300"}`}>
                  <ListChecks size={42} className={`mx-auto mb-3 ${lightCanvas ? "text-gray-400" : "text-gray-500"}`} />
                  <h2 className={`text-lg font-semibold ${lightCanvas ? "text-gray-950" : "text-white"}`}>
                    {reviewRun ? "本实验候选已复核完成" : activeWork ? activeWork.view === "skipped" ? "没有暂时跳过的图片" : "本次范围已处理完" : queueScope === "current_filter" && hasActiveTriageFilters
                      ? "没有符合筛选条件的图片"
                      : queueScope === "current_filter" && (stats?.total_images ?? 0) === 0
                        ? "数据集中没有可分拣图片"
                        : "这个队列已经处理完了"}
                  </h2>
                  <p className={`mt-2 text-sm leading-6 ${lightCanvas ? "text-gray-600" : "text-gray-400"}`}>
                    {reviewRun ? "本实验候选已复核完成" : activeWork ? "可回看本次全部、处理跳过的图片，或检查新增与变化。暂时跳过不会改变人工判定。" : queueScope === "current_filter" && hasActiveTriageFilters
                      ? "请调整或清除筛选条件，当前数据不会被修改。"
                      : queueScope === "current_filter" && (stats?.total_images ?? 0) === 0
                        ? "请先返回数据集扫描图片，再开始快速分拣。"
                        : queueScope === "pending"
                      ? "目前没有待定图片；遇到边界不清的样本时，可用“待定复看”暂存。"
                      : pendingCount > 0
                        ? `还有 ${pendingCount} 张待定图片需要复看。`
                        : dataset?.workflow_profile === "industrial_anomaly"
                          ? "没有待复看的图片，可继续分组、快速验证或导出训练包。"
                          : "没有待复看的图片，可检查全部结果或开始导出。"}
                  </p>
                  {queueScope === "current_filter" && hasActiveTriageFilters && (
                    <button
                      type="button"
                      onClick={clearTriageFilters}
                      className="mt-4 inline-flex min-h-10 items-center rounded-lg bg-white px-4 text-sm font-semibold text-gray-950 hover:bg-gray-100"
                    >
                      清除筛选
                    </button>
                  )}
                  {!reviewRun && !(queueScope === "current_filter" && hasActiveTriageFilters)
                    && queueScope !== "pending" && pendingCount > 0 && (
                    <button
                      type="button"
                      onClick={() => selectQueue("pending")}
                      className="mt-4 inline-flex min-h-10 items-center rounded-lg bg-violet-100 px-4 text-sm font-semibold text-violet-950 hover:bg-violet-200"
                    >
                      复看待定（{pendingCount}）
                    </button>
                  )}
                  {!reviewRun && !(queueScope === "current_filter" && hasActiveTriageFilters)
                    && (stats?.total_images ?? 0) > 0 && (
                    <Link to={dataset?.workflow_profile === "industrial_anomaly" ? `/datasets/${datasetId}` : `/datasets/${datasetId}?directoryExport=1`} className="mt-4 inline-flex min-h-10 items-center rounded-lg bg-white px-4 text-sm font-semibold text-gray-950 hover:bg-gray-100">
                      {dataset?.workflow_profile === "industrial_anomaly" ? "返回数据准备" : "导出分拣目录 / ZIP"}
                    </Link>
                  )}
                </div>
              )}
            </div>
            <div className={`flex min-h-14 flex-wrap items-center justify-between gap-3 border-t px-4 transition-colors duration-200 ${lightCanvas ? "border-gray-200" : "border-white/10"}`}>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-label="缩小图片"
                  onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))}
                  className={`rounded-md p-2 ${lightCanvas ? "text-gray-600 hover:bg-gray-100 hover:text-gray-950" : "text-gray-300 hover:bg-white/10 hover:text-white"}`}
                ><ZoomOut size={18} /></button>
                <span className={`w-12 text-center text-xs ${lightCanvas ? "text-gray-500" : "text-gray-400"}`}>{Math.round(zoom * 100)}%</span>
                <button
                  type="button"
                  aria-label="放大图片"
                  onClick={() => setZoom((value) => Math.min(3, value + 0.25))}
                  className={`rounded-md p-2 ${lightCanvas ? "text-gray-600 hover:bg-gray-100 hover:text-gray-950" : "text-gray-300 hover:bg-white/10 hover:text-white"}`}
                ><ZoomIn size={18} /></button>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={!navigation?.previous_sample || saving}
                  onClick={() => requestNavigation(() => replaceSearchParams({ sample: navigation?.previous_sample?.id ?? null }))}
                  className={`inline-flex min-h-10 items-center gap-1 rounded-lg border px-3 text-sm disabled:opacity-30 ${lightCanvas ? "border-gray-300 text-gray-700 hover:bg-gray-100" : "border-white/15 text-gray-200 hover:bg-white/10"}`}
                ><ChevronLeft size={17} /> 上一张</button>
                <button
                  type="button"
                  disabled={!navigation?.next_sample || saving}
                  onClick={() => requestNavigation(() => replaceSearchParams({ sample: navigation?.next_sample?.id ?? null }))}
                  className={`inline-flex min-h-10 items-center gap-1 rounded-lg border px-3 text-sm disabled:opacity-30 ${lightCanvas ? "border-gray-300 text-gray-700 hover:bg-gray-100" : "border-white/15 text-gray-200 hover:bg-white/10"}`}
                >下一张 <ChevronRight size={17} /></button>
              </div>
            </div>
          </section>

          <aside className="min-w-0 rounded-2xl border border-line bg-white shadow-sm">
            <div className="flex border-b border-line p-1.5">
              <button
                type="button"
                onClick={() => requestNavigation(() => changeMode("quick"))}
                className={`min-h-10 flex-1 rounded-lg text-sm font-semibold ${mode === "quick" ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-50"}`}
              >快速判定</button>
              <button
                type="button"
                onClick={() => changeMode("detail")}
                className={`min-h-10 flex-1 rounded-lg text-sm font-semibold ${mode === "detail" ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-50"}`}
              >详细分拣</button>
            </div>

            {currentSample && (
              <div className={`mx-4 mt-4 flex items-center justify-between gap-3 rounded-xl border px-4 py-3 ${currentResultStyles.card}`}>
                <div>
                  <div className="text-xs font-semibold text-gray-500">
                    {triage?.triage_status === "untriaged" ? "本张状态" : "本张已保存"}
                  </div>
                  <div className={`mt-0.5 text-xl font-bold ${currentResultStyles.label}`}>
                    {currentResult.label}
                  </div>
                </div>
                {triage?.outdated && (
                  <span className="rounded-full border border-amber-300 bg-white px-2.5 py-1 text-xs font-semibold text-amber-800">
                    待复核
                  </span>
                )}
              </div>
            )}

            {triage?.outdated && (
              <div className="mx-4 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                图片内容或分拣规则已变化，请重新确认本张结果。
              </div>
            )}

            {mode === "quick" ? (
              <div className="space-y-4 p-4">
                <div>
                  <h2 className="font-semibold">单键判定</h2>
                  <p className="mt-1 text-xs leading-5 text-gray-500">按数字键立即保存并进入下一张；空格仅跳过。</p>
                </div>
                <div className="grid gap-3">
                  {splitOk ? (
                    <>
                      <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("clear")} className="flex min-h-16 items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 px-4 text-left hover:bg-emerald-100 disabled:opacity-40">
                        <span><span className="block font-semibold text-emerald-950">{okGradeCopy.clear}</span><span className="mt-1 block text-xs text-emerald-700">{policy?.clear_ok_definition}</span></span><kbd className="rounded bg-emerald-900 px-2 py-1 text-sm font-bold text-white">1</kbd>
                      </button>
                      <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("borderline")} className="flex min-h-16 items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-4 text-left hover:bg-amber-100 disabled:opacity-40">
                        <span><span className="block font-semibold text-amber-950">{okGradeCopy.borderline}</span><span className="mt-1 block text-xs text-amber-700">可在详细模式记录轻微缺陷</span></span><kbd className="rounded bg-amber-900 px-2 py-1 text-sm font-bold text-white">2</kbd>
                      </button>
                    </>
                  ) : (
                    <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("ok")} className="flex min-h-16 items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 px-4 text-left hover:bg-emerald-100 disabled:opacity-40">
                      <span><span className="block font-semibold text-emerald-950">OK</span><span className="mt-1 block text-xs text-emerald-700">统一判为合格，不再区分等级</span></span><kbd className="rounded bg-emerald-900 px-2 py-1 text-sm font-bold text-white">1</kbd>
                    </button>
                  )}
                  <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("ng")} className="flex min-h-16 items-center justify-between rounded-xl border border-red-200 bg-red-50 px-4 text-left hover:bg-red-100 disabled:opacity-40">
                    <span><span className="block font-semibold text-red-950">NG</span><span className="mt-1 block text-xs text-red-700">{NG_GROUPING_DESCRIPTIONS[ngGrouping]}</span></span><kbd className="rounded bg-red-900 px-2 py-1 text-sm font-bold text-white">{splitOk ? "3" : "2"}</kbd>
                  </button>
                  <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("pending")} className="flex min-h-16 items-center justify-between rounded-xl border border-violet-200 bg-violet-50 px-4 text-left hover:bg-violet-100 disabled:opacity-40">
                    <span><span className="block font-semibold text-violet-950">待定复看</span><span className="mt-1 block text-xs text-violet-700">信息不足或边界不清时暂存</span></span><kbd className="rounded bg-violet-900 px-2 py-1 text-sm font-bold text-white">{splitOk ? "4" : "3"}</kbd>
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-5 p-4">
                <div>
                  <label className="text-sm font-semibold" htmlFor="triage-status">判定</label>
                  <select
                    id="triage-status"
                    value={draft.status}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      status: event.target.value as TriageStatus,
                      okGrade: event.target.value === "ok" && splitOk ? current.okGrade ?? "borderline" : null
                    }))}
                    className="mt-2 min-h-11 w-full rounded-lg border border-line bg-white px-3 text-sm"
                  >
                    {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>

                {draft.status === "ok" && splitOk && (
                  <fieldset>
                    <legend className="text-sm font-semibold">OK 等级</legend>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {(["clear", "borderline"] as OkGrade[]).map((grade) => (
                        <button
                          key={grade}
                          type="button"
                          onClick={() => setDraft((current) => ({ ...current, okGrade: grade }))}
                          className={`min-h-11 rounded-lg border text-sm font-medium ${draft.okGrade === grade ? "border-gray-900 bg-gray-900 text-white" : "border-line bg-white text-gray-700"}`}
                        >{okGradeCopy[grade]}</button>
                      ))}
                    </div>
                  </fieldset>
                )}

                {(showDefectTypes || showDefectSeverity) && (
                  <>
                    {showDefectSeverity && (
                      <fieldset>
                        <legend className="text-sm font-semibold">缺陷程度</legend>
                        <div className="mt-2 grid grid-cols-3 gap-2">
                          {(["mild", "moderate", "severe"] as DefectSeverity[]).map((severity) => (
                            <button
                              key={severity}
                              type="button"
                              onClick={() => setDraft((current) => ({ ...current, severity: current.severity === severity ? null : severity }))}
                              className={`min-h-10 rounded-lg border text-sm ${draft.severity === severity ? "border-red-700 bg-red-50 font-semibold text-red-800" : "border-line text-gray-700"}`}
                            >{SEVERITY_LABELS[severity]}</button>
                          ))}
                        </div>
                      </fieldset>
                    )}

                    {showDefectTypes && (
                      <>
                        <fieldset>
                          <legend className="text-sm font-semibold">缺陷类型（可多选）</legend>
                          <div className="mt-2 max-h-44 space-y-1 overflow-auto rounded-lg border border-line p-2">
                            {activeDefectTypes.length === 0 && <p className="px-2 py-3 text-xs text-gray-500">还没有缺陷类型，可在下方快速新建。</p>}
                            {activeDefectTypes.map((item) => (
                              <label key={item.id} className="flex min-h-9 cursor-pointer items-center gap-2 rounded-md px-2 text-sm hover:bg-gray-50" style={{ paddingLeft: item.parent_id ? 28 : 8 }}>
                                <input type="checkbox" checked={draft.defectTypeIds.includes(item.id)} onChange={() => toggleDefectType(item.id)} />
                                <span className={item.parent_id ? "text-gray-600" : "font-medium"}>{item.name}</span>
                              </label>
                            ))}
                          </div>
                        </fieldset>

                        {draft.defectTypeIds.length > 1 && (
                          <div>
                            <label htmlFor="primary-defect" className="text-sm font-semibold">主要缺陷</label>
                            <select id="primary-defect" value={draft.primaryDefectTypeId ?? ""} onChange={(event) => setDraft((current) => ({ ...current, primaryDefectTypeId: Number(event.target.value) || null }))} className="mt-2 min-h-10 w-full rounded-lg border border-line bg-white px-3 text-sm">
                              {activeDefectTypes.filter((item) => draft.defectTypeIds.includes(item.id)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                            </select>
                          </div>
                        )}

                        <div className="rounded-lg bg-gray-50 p-3">
                          <div className="text-xs font-semibold text-gray-700">快速新增缺陷类型</div>
                          <div className="mt-2 grid gap-2">
                            <input value={newDefectName} onChange={(event) => setNewDefectName(event.target.value)} placeholder="例如：划痕、脏污" className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm" />
                            <select value={newDefectParent ?? ""} onChange={(event) => setNewDefectParent(Number(event.target.value) || null)} className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm">
                              <option value="">作为一级类型</option>
                              {rootDefectTypes.map((item) => <option key={item.id} value={item.id}>作为“{item.name}”的子类型</option>)}
                            </select>
                            <button type="button" onClick={() => void addDefectType()} disabled={!newDefectName.trim() || creatingDefect} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white text-sm font-medium hover:bg-gray-100 disabled:opacity-40">
                              {creatingDefect ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} 新建并选中
                            </button>
                          </div>
                        </div>
                      </>
                    )}
                  </>
                )}

                <div>
                  <label htmlFor="triage-note" className="text-sm font-semibold">备注</label>
                  <textarea id="triage-note" rows={3} maxLength={4000} disabled={!triage || saving || loading} value={draft.note} onChange={(event) => setDraft((current) => ({ ...current, note: event.target.value }))} placeholder="记录边界情况、客户要求或复看原因" className="mt-2 w-full resize-y rounded-lg border border-line p-3 text-sm disabled:opacity-40" />
                  {dataset && <TriageReasonChips key={`${dataset.id}:${dataset.created_at}`} storageKey={`dataset-manager.triage.reasons.${dataset.id}.${dataset.created_at}`} disabled={!triage || saving || loading} onInsert={(reason) => {
                    const next = draft.note ? `${draft.note}${draft.note.endsWith("\n") ? "" : "\n"}${reason}` : reason;
                    if (next.length > 4000) { setError("备注最多 4000 字，请精简后再添加理由。"); return; }
                    setDraft((current) => ({ ...current, note: next }));
                  }} />}
                  {hasUnsavedDraft && <p role="status" className="mt-2 text-xs text-amber-800">本张有未保存修改</p>}
                </div>

                <button type="button" onClick={() => void saveDetail()} disabled={!triage || saving || !imageReady} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-40">
                  {saving ? <Loader2 size={18} className="animate-spin" /> : <Check size={18} />} 保存并下一张
                </button>
              </div>
            )}
          </aside>
        </div>
      </section>

      {toasts.length > 0 && (
        <div
          aria-live="polite"
          aria-label="快速分拣消息"
          className="pointer-events-none fixed bottom-3 left-3 z-50 flex w-80 max-w-[calc(100vw-6rem)] flex-col gap-2 sm:bottom-5 sm:left-5 sm:max-w-sm"
        >
          {toasts.map((toast) => (
            <div
              key={toast.id}
              role="status"
              className={`pointer-events-auto rounded-xl border px-4 py-3 shadow-lg backdrop-blur ${toast.exiting ? "triage-toast-exit" : "triage-toast-enter"} ${toast.tone === "success" ? "border-emerald-200 bg-emerald-50/95 text-emerald-950" : "border-sky-200 bg-sky-50/95 text-sky-950"}`}
            >
              <div className="flex items-start gap-3">
                <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white ${toast.tone === "success" ? "bg-emerald-600" : "bg-sky-600"}`}>
                  <Check size={15} strokeWidth={3} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold leading-6">{toast.message}</div>
                  {toast.action === "pending" && queueScope !== "pending" && (
                    <button
                      type="button"
                      onClick={() => selectQueue("pending")}
                      className="mt-1 text-xs font-semibold text-violet-800 underline-offset-2 hover:underline"
                    >
                      去复看待定{pendingCount > 0 ? `（${pendingCount}）` : ""}
                    </button>
                  )}
                </div>
                {!toast.exiting && (
                  <button
                    type="button"
                    aria-label="关闭消息，本次快速分拣不再弹出"
                    title="关闭并在本次快速分拣中静默消息"
                    onClick={() => {
                      setToasts([]);
                      setToastsMuted(true);
                    }}
                    className="-mr-1 -mt-1 rounded-md p-1 text-current opacity-60 hover:bg-black/5 hover:opacity-100"
                  >
                    <X size={16} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
