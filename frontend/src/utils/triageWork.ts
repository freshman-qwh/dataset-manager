import type { WorkSampleState } from "../api/triageWork";

export type WorkView = "todo" | "skipped" | "all";
export interface TriageWork {
  version: 1;
  datasetId: number;
  datasetCreatedAt: string;
  query: string;
  sampleIds: number[];
  completed: Record<string, WorkSampleState>;
  skipped: number[];
  currentId: number | null;
  view: WorkView;
  mode: "quick" | "detail";
}

const validId = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
export const workStorageKey = (datasetId: number) => `dataset-manager.triage-work.v1.${datasetId}`;

/** Only supported local filter values are restored; never restore a return URL or review run. */
export function workQuery(params: URLSearchParams): string {
  const result = new URLSearchParams();
  const queue = params.get("queue");
  result.set("queue", ["pending", "current_filter", "current_split"].includes(queue ?? "") ? queue! : "untriaged");
  for (const [key, values] of Object.entries({ status: ["untriaged", "pending", "ok", "ng"], okGrade: ["clear", "borderline"], severity: ["mild", "moderate", "severe"], split: ["train", "val", "test", "unassigned"] })) {
    const value = params.get(key);
    if (value && values.includes(value)) result.set(key, value);
  }
  const defect = Number(params.get("defectType"));
  if (validId(defect)) result.set("defectType", String(defect));
  const search = params.get("q");
  if (search && search.length <= 300) result.set("q", search);
  return result.toString();
}

export function readTriageWork(datasetId: number, createdAt: string): TriageWork | null {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(workStorageKey(datasetId)) ?? "null");
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    const value = raw as TriageWork;
    if (value.version !== 1 || value.datasetId !== datasetId || value.datasetCreatedAt !== createdAt || typeof value.query !== "string" || value.query.length > 4000 || !Array.isArray(value.sampleIds) || value.sampleIds.length > 10000 || !value.sampleIds.every(validId)) return null;
    const ids = [...new Set(value.sampleIds)];
    const completed: Record<string, WorkSampleState> = {};
    for (const id of ids) {
      const state = value.completed?.[id];
      if (state && state.sample_id === id && Number.isSafeInteger(state.triage_version) && state.triage_version >= 0 && typeof state.file_hash === "string" && ["ok", "ng", "pending", "untriaged"].includes(state.triage_status)) completed[id] = state;
    }
    return { version: 1, datasetId, datasetCreatedAt: createdAt, query: workQuery(new URLSearchParams(value.query)), sampleIds: ids, completed,
      skipped: Array.isArray(value.skipped) ? ids.filter(id => value.skipped.includes(id) && !completed[id]) : [],
      currentId: validId(value.currentId) && ids.includes(value.currentId) ? value.currentId : null,
      view: value.view === "skipped" || value.view === "all" ? value.view : "todo", mode: value.mode === "detail" ? "detail" : "quick" };
  } catch { return null; }
}

export function writeTriageWork(work: TriageWork): boolean {
  try { localStorage.setItem(workStorageKey(work.datasetId), JSON.stringify(work)); return true; }
  catch { return false; }
}

export function workIds(work: TriageWork): number[] {
  return work.sampleIds.filter(id => work.view === "all" || (work.view === "skipped" ? work.skipped.includes(id) : !work.completed[id] && !work.skipped.includes(id)));
}

export function completeWorkSample(work: TriageWork, state: WorkSampleState): TriageWork {
  const completed = { ...work.completed };
  if (state.triage_status === "untriaged") delete completed[state.sample_id];
  else completed[state.sample_id] = state;
  return { ...work, completed, skipped: work.skipped.filter(id => id !== state.sample_id) };
}

/** Invalidates progress only; never writes judgments back to the server. */
export function reconcileWork(work: TriageWork, states: WorkSampleState[]): { work: TriageWork; changed: number; removed: number } {
  const byId = new Map(states.map(state => [state.sample_id, state]));
  let changed = 0;
  const completed: Record<string, WorkSampleState> = {};
  for (const id of work.sampleIds) {
    const before = work.completed[id], now = byId.get(id);
    if (!before || !now) continue;
    if (before.triage_version === now.triage_version && before.file_hash === now.file_hash && before.triage_policy_version === now.triage_policy_version && !now.triage_outdated && (!now.file_status || now.file_status === "normal")) completed[id] = now;
    else changed++;
  }
  const sampleIds = work.sampleIds.filter(id => byId.has(id));
  return { work: { ...work, sampleIds, completed, skipped: work.skipped.filter(id => byId.has(id)), currentId: work.currentId && byId.has(work.currentId) ? work.currentId : null }, changed, removed: work.sampleIds.length - sampleIds.length };
}
