import axios from "axios";
import {
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  ListChecks,
  Loader2,
  Plus,
  RotateCcw,
  ZoomIn,
  ZoomOut
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  createDefectType,
  getDataset,
  getSampleFileUrl,
  getSampleTriage,
  getTriageNavigation,
  getTriagePolicy,
  getTriageStats,
  listDefectTypes,
  replaceSampleTriage
} from "../api/client";
import type { Dataset, Sample } from "../types/dataset";
import type {
  DefectSeverity,
  DefectType,
  OkGrade,
  SampleTriage,
  SampleTriageWrite,
  TriageNavigation,
  TriagePolicy,
  TriageQueueScope,
  TriageStats,
  TriageStatus
} from "../types/triage";

const QUEUE_LABELS: Record<TriageQueueScope, string> = {
  untriaged: "未分拣",
  pending: "待定复看",
  current_filter: "全部图片",
  current_split: "当前划分"
};

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
  const routeParams = useParams();
  const datasetId = Number(routeParams.datasetId);
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSampleId = Number(searchParams.get("sample")) || null;
  const requestedQueue = searchParams.get("queue");
  const queueScope: TriageQueueScope =
    requestedQueue === "pending"
    || requestedQueue === "current_filter"
    || requestedQueue === "current_split"
      ? requestedQueue
      : "untriaged";
  const queueSplit = searchParams.get("split") || undefined;
  const navigationSampleId = useMemo(() => {
    if (requestedSampleId) return requestedSampleId;
    try {
      const stored = JSON.parse(
        window.localStorage.getItem(`dataset-manager.triage.${datasetId}`) ?? "null"
      ) as { sampleId?: number; queueScope?: TriageQueueScope } | null;
      return stored?.queueScope === queueScope && Number.isInteger(stored.sampleId)
        ? stored.sampleId ?? null
        : null;
    } catch {
      return null;
    }
  }, [datasetId, queueScope, requestedSampleId]);

  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [policy, setPolicy] = useState<TriagePolicy | null>(null);
  const [stats, setStats] = useState<TriageStats | null>(null);
  const [defectTypes, setDefectTypes] = useState<DefectType[]>([]);
  const [navigation, setNavigation] = useState<TriageNavigation | null>(null);
  const [triage, setTriage] = useState<SampleTriage | null>(null);
  const [draft, setDraft] = useState<TriageDraft>(blankDraft);
  const [mode, setMode] = useState<"quick" | "detail">("quick");
  const [zoom, setZoom] = useState(1);
  const [imageReady, setImageReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [undoRecord, setUndoRecord] = useState<UndoRecord | null>(null);
  const [newDefectName, setNewDefectName] = useState("");
  const [newDefectParent, setNewDefectParent] = useState<number | null>(null);
  const [creatingDefect, setCreatingDefect] = useState(false);
  const requestIdRef = useRef(0);
  const savingRef = useRef(false);
  const actionRef = useRef<(action: "clear" | "borderline" | "ng" | "pending") => void>();
  const undoRef = useRef<() => void>();

  const currentSample = navigation?.current_sample ?? null;
  const activeDefectTypes = useMemo(
    () => defectTypes.filter((item) => item.is_active),
    [defectTypes]
  );
  const rootDefectTypes = useMemo(
    () => activeDefectTypes.filter((item) => item.parent_id === null),
    [activeDefectTypes]
  );
  const progressDone = stats
    ? (stats.by_status.ok ?? 0) + (stats.by_status.ng ?? 0) + (stats.by_status.pending ?? 0)
    : 0;

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
      .then(([datasetValue, policyValue, statsValue, defectTypeValues]) => {
        if (cancelled) return;
        setDataset(datasetValue);
        setPolicy(policyValue);
        setStats(statsValue);
        setDefectTypes(defectTypeValues);
      })
      .catch((loadError) => {
        if (!cancelled) setError(errorMessage(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  useEffect(() => {
    if (!Number.isInteger(datasetId) || datasetId <= 0) return;
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    getTriageNavigation({
      datasetId,
      sampleId: navigationSampleId,
      queueScope,
      split: queueSplit
    })
      .then(async (navigationValue) => {
        if (requestId !== requestIdRef.current) return;
        setNavigation(navigationValue);
        const sample = navigationValue.current_sample;
        if (!sample) {
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
        try {
          window.localStorage.setItem(
            `dataset-manager.triage.${datasetId}`,
            JSON.stringify({ sampleId: sample.id, queueScope })
          );
        } catch {
          // 浏览器禁用本地存储时不影响分拣。
        }
      })
      .catch((loadError) => {
        if (requestId === requestIdRef.current) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });
  }, [datasetId, navigationSampleId, queueScope, queueSplit, replaceSearchParams, requestedSampleId]);

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
    options: { advance: boolean; message: string }
  ) => {
    if (!currentSample || !triage || savingRef.current) return;
    savingRef.current = true;
    const nextSampleId = navigation?.next_sample?.id ?? null;
    const before = triage;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await replaceSampleTriage(currentSample.id, {
        ...payload,
        expected_version: triage.triage_version,
        expected_file_hash: triage.file_hash
      });
      setUndoRecord({ sample: currentSample, before, savedVersion: saved.triage_version });
      setTriage(saved);
      setDraft(draftFromTriage(saved));
      setNotice(options.message);
      if (options.advance) {
        advanceAfterSave(nextSampleId);
      }
      void getTriageStats(datasetId).then(setStats).catch(() => undefined);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [advanceAfterSave, currentSample, datasetId, navigation?.next_sample?.id, saving, triage]);

  const quickAction = useCallback((action: "clear" | "borderline" | "ng" | "pending") => {
    const common = {
      defect_type_ids: [] as number[],
      primary_defect_type_id: null,
      triage_note: null,
      defect_severity: null
    };
    if (action === "clear") {
      void savePayload(
        { ...common, triage_status: "ok", ok_grade: "clear" },
        { advance: true, message: "已标记为完全 OK。" }
      );
    } else if (action === "borderline") {
      void savePayload(
        { ...common, triage_status: "ok", ok_grade: "borderline" },
        { advance: true, message: "已标记为勉强 OK。" }
      );
    } else if (action === "ng") {
      void savePayload(
        { ...common, triage_status: "ng", ok_grade: null },
        { advance: true, message: "已标记为 NG，可稍后补充缺陷细节。" }
      );
    } else {
      void savePayload(
        { ...common, triage_status: "pending", ok_grade: null },
        { advance: true, message: "已加入待定复看队列。" }
      );
    }
  }, [savePayload]);
  actionRef.current = quickAction;

  const saveDetail = useCallback(() => {
    let nextDraft = draft;
    if (draft.status === "untriaged") {
      nextDraft = blankDraft();
    } else if (draft.status === "ok" && draft.okGrade === "clear") {
      nextDraft = { ...draft, severity: null, defectTypeIds: [], primaryDefectTypeId: null };
    }
    if (nextDraft.status === "ok" && !nextDraft.okGrade) {
      setError("请选择完全 OK 或勉强 OK。");
      return;
    }
    void savePayload(
      {
        triage_status: nextDraft.status,
        ok_grade: nextDraft.status === "ok" ? nextDraft.okGrade : null,
        defect_severity: nextDraft.severity,
        defect_type_ids: nextDraft.defectTypeIds,
        primary_defect_type_id: nextDraft.primaryDefectTypeId,
        triage_note: nextDraft.note.trim() || null
      },
      { advance: true, message: "分拣结果与缺陷细节已保存。" }
    );
  }, [draft, savePayload]);

  const undoLast = useCallback(async () => {
    if (!undoRecord || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      await replaceSampleTriage(
        undoRecord.sample.id,
        writeFromTriage(undoRecord.before, undoRecord.savedVersion)
      );
      setUndoRecord(null);
      setNotice(`已撤销 ${undoRecord.sample.filename} 的上一次分拣。`);
      setStats(await getTriageStats(datasetId));
      replaceSearchParams({ sample: undoRecord.sample.id });
    } catch (undoError) {
      setError(errorMessage(undoError));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [datasetId, replaceSearchParams, saving, undoRecord]);
  undoRef.current = () => void undoLast();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.isComposing || isTypingTarget(event.target)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undoRef.current?.();
        return;
      }
      if (savingRef.current || loading || !imageReady || mode !== "quick") return;
      const actions = actionRef.current;
      if (event.key === "1") actions?.("clear");
      else if (event.key === "2") actions?.("borderline");
      else if (event.key === "3") actions?.("ng");
      else if (event.key === "4") actions?.("pending");
      else if (event.key === " " && navigation?.next_sample) {
        event.preventDefault();
        replaceSearchParams({ sample: navigation.next_sample.id });
      } else {
        return;
      }
      event.preventDefault();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [imageReady, loading, mode, navigation?.next_sample, replaceSearchParams]);

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

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="flex min-w-0 items-center gap-4">
            <Link
              to={`/datasets/${datasetId}`}
              className="inline-flex min-h-11 shrink-0 items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-950"
            >
              <ArrowLeft size={18} /> 返回数据集
            </Link>
            <div className="hidden h-7 w-px bg-line sm:block" />
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold">快速分拣 · {dataset?.name ?? "加载中"}</h1>
              <p className="text-xs text-gray-500">规则版本 {policy?.version ?? "-"} · 保存成功后自动进入下一张</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void undoLast()}
              disabled={!undoRecord || saving}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RotateCcw size={16} /> 撤销 Ctrl+Z
            </button>
            <select
              aria-label="分拣队列"
              value={queueScope}
              onChange={(event) => {
                const nextQueue = event.target.value as TriageQueueScope;
                replaceSearchParams({
                  queue: nextQueue,
                  sample: null,
                  split: nextQueue === "current_split"
                    ? currentSample?.split ?? "unassigned"
                    : null
                });
              }}
              className="min-h-10 rounded-lg border border-line bg-white px-3 text-sm"
            >
              {Object.entries(QUEUE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-[1600px] px-5 py-4">
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded-xl border border-line bg-white px-4 py-3">
            <div className="text-xs text-gray-500">已处理 / 图片</div>
            <div className="mt-1 text-xl font-semibold">{progressDone} / {stats?.total_images ?? 0}</div>
          </div>
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <div className="text-xs text-emerald-700">完全 OK</div>
            <div className="mt-1 text-xl font-semibold text-emerald-900">{stats?.by_ok_grade.clear ?? 0}</div>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <div className="text-xs text-amber-700">勉强 OK</div>
            <div className="mt-1 text-xl font-semibold text-amber-900">{stats?.by_ok_grade.borderline ?? 0}</div>
          </div>
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
        </div>

        {error && (
          <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <CircleAlert size={18} className="mt-0.5 shrink-0" /> {error}
          </div>
        )}
        {notice && !error && (
          <div aria-live="polite" className="mb-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <Check size={18} /> {notice}
          </div>
        )}

        <div className="grid min-h-[680px] gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
          <section className="relative flex min-h-[620px] min-w-0 flex-col overflow-hidden rounded-2xl border border-line bg-gray-950 shadow-sm">
            <div className="flex min-h-12 items-center justify-between gap-3 border-b border-white/10 px-4 text-sm text-gray-300">
              <div className="min-w-0 truncate">
                {currentSample ? currentSample.relative_path : QUEUE_LABELS[queueScope]}
              </div>
              <div className="shrink-0">
                {navigation?.current_index !== null && navigation?.current_index !== undefined
                  ? `${navigation.current_index + 1} / ${navigation.total}`
                  : `${navigation?.total ?? 0} 张`}
              </div>
            </div>
            <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto p-5">
              {loading ? (
                <div className="flex items-center gap-2 text-sm text-gray-300"><Loader2 className="animate-spin" size={20} /> 加载图片…</div>
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
                  className="max-h-[calc(100vh-270px)] max-w-full select-none object-contain transition-transform"
                />
              ) : (
                <div className="max-w-md text-center text-gray-300">
                  <ListChecks size={42} className="mx-auto mb-3 text-gray-500" />
                  <h2 className="text-lg font-semibold text-white">这个队列已经处理完了</h2>
                  <p className="mt-2 text-sm leading-6 text-gray-400">可切换到“待定复看”或“全部图片”检查已有结果。</p>
                </div>
              )}
            </div>
            <div className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-t border-white/10 px-4">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-label="缩小图片"
                  onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))}
                  className="rounded-md p-2 text-gray-300 hover:bg-white/10 hover:text-white"
                ><ZoomOut size={18} /></button>
                <span className="w-12 text-center text-xs text-gray-400">{Math.round(zoom * 100)}%</span>
                <button
                  type="button"
                  aria-label="放大图片"
                  onClick={() => setZoom((value) => Math.min(3, value + 0.25))}
                  className="rounded-md p-2 text-gray-300 hover:bg-white/10 hover:text-white"
                ><ZoomIn size={18} /></button>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={!navigation?.previous_sample || saving}
                  onClick={() => replaceSearchParams({ sample: navigation?.previous_sample?.id ?? null })}
                  className="inline-flex min-h-10 items-center gap-1 rounded-lg border border-white/15 px-3 text-sm text-gray-200 hover:bg-white/10 disabled:opacity-30"
                ><ChevronLeft size={17} /> 上一张</button>
                <button
                  type="button"
                  disabled={!navigation?.next_sample || saving}
                  onClick={() => replaceSearchParams({ sample: navigation?.next_sample?.id ?? null })}
                  className="inline-flex min-h-10 items-center gap-1 rounded-lg border border-white/15 px-3 text-sm text-gray-200 hover:bg-white/10 disabled:opacity-30"
                >下一张 <ChevronRight size={17} /></button>
              </div>
            </div>
          </section>

          <aside className="min-w-0 rounded-2xl border border-line bg-white shadow-sm">
            <div className="flex border-b border-line p-1.5">
              <button
                type="button"
                onClick={() => setMode("quick")}
                className={`min-h-10 flex-1 rounded-lg text-sm font-semibold ${mode === "quick" ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-50"}`}
              >快速判定</button>
              <button
                type="button"
                onClick={() => setMode("detail")}
                className={`min-h-10 flex-1 rounded-lg text-sm font-semibold ${mode === "detail" ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-50"}`}
              >详细分拣</button>
            </div>

            {triage?.outdated && (
              <div className="m-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
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
                  <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("clear")} className="flex min-h-16 items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 px-4 text-left hover:bg-emerald-100 disabled:opacity-40">
                    <span><span className="block font-semibold text-emerald-950">完全 OK</span><span className="mt-1 block text-xs text-emerald-700">{policy?.clear_ok_definition}</span></span><kbd className="rounded bg-emerald-900 px-2 py-1 text-sm font-bold text-white">1</kbd>
                  </button>
                  <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("borderline")} className="flex min-h-16 items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-4 text-left hover:bg-amber-100 disabled:opacity-40">
                    <span><span className="block font-semibold text-amber-950">勉强 OK</span><span className="mt-1 block text-xs text-amber-700">可在详细模式记录轻微缺陷</span></span><kbd className="rounded bg-amber-900 px-2 py-1 text-sm font-bold text-white">2</kbd>
                  </button>
                  <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("ng")} className="flex min-h-16 items-center justify-between rounded-xl border border-red-200 bg-red-50 px-4 text-left hover:bg-red-100 disabled:opacity-40">
                    <span><span className="block font-semibold text-red-950">NG</span><span className="mt-1 block text-xs text-red-700">先判缺陷，后续可补类型与程度</span></span><kbd className="rounded bg-red-900 px-2 py-1 text-sm font-bold text-white">3</kbd>
                  </button>
                  <button type="button" disabled={!triage || saving || !imageReady} onClick={() => quickAction("pending")} className="flex min-h-16 items-center justify-between rounded-xl border border-violet-200 bg-violet-50 px-4 text-left hover:bg-violet-100 disabled:opacity-40">
                    <span><span className="block font-semibold text-violet-950">待定复看</span><span className="mt-1 block text-xs text-violet-700">信息不足或边界不清时暂存</span></span><kbd className="rounded bg-violet-900 px-2 py-1 text-sm font-bold text-white">4</kbd>
                  </button>
                </div>
                <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs leading-5 text-gray-600">
                  当前结果：{triage ? STATUS_LABELS[triage.triage_status] : "-"}
                  {triage?.ok_grade === "clear" ? " · 完全 OK" : triage?.ok_grade === "borderline" ? " · 勉强 OK" : ""}
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
                      okGrade: event.target.value === "ok" ? current.okGrade ?? "borderline" : null
                    }))}
                    className="mt-2 min-h-11 w-full rounded-lg border border-line bg-white px-3 text-sm"
                  >
                    {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>

                {draft.status === "ok" && (
                  <fieldset>
                    <legend className="text-sm font-semibold">OK 等级</legend>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {(["clear", "borderline"] as OkGrade[]).map((grade) => (
                        <button
                          key={grade}
                          type="button"
                          onClick={() => setDraft((current) => ({ ...current, okGrade: grade }))}
                          className={`min-h-11 rounded-lg border text-sm font-medium ${draft.okGrade === grade ? "border-gray-900 bg-gray-900 text-white" : "border-line bg-white text-gray-700"}`}
                        >{grade === "clear" ? "完全 OK" : "勉强 OK"}</button>
                      ))}
                    </div>
                  </fieldset>
                )}

                {!(draft.status === "ok" && draft.okGrade === "clear") && draft.status !== "untriaged" && (
                  <>
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

                <div>
                  <label htmlFor="triage-note" className="text-sm font-semibold">备注</label>
                  <textarea id="triage-note" rows={3} value={draft.note} onChange={(event) => setDraft((current) => ({ ...current, note: event.target.value }))} placeholder="记录边界情况、客户要求或复看原因" className="mt-2 w-full resize-y rounded-lg border border-line p-3 text-sm" />
                </div>

                <button type="button" onClick={saveDetail} disabled={!triage || saving || !imageReady} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-40">
                  {saving ? <Loader2 size={18} className="animate-spin" /> : <Check size={18} />} 保存并下一张
                </button>
              </div>
            )}
          </aside>
        </div>
      </section>
    </main>
  );
}
