export const WORKBENCH_STORAGE_KEY = "dataset-manager:workbench:v1";
export const LEGACY_BROWSE_STORAGE_KEY = "dataset-manager:local-browse-locations:v1";
export const MAX_RECENT_DATASETS = 8;
export const MAX_PINNED_DATASETS = 20;
const CHANGE_EVENT = "dataset-manager:workbench-changed";

export interface WorkbenchVisit {
  datasetId: number;
  openedAt: number;
  browseQuery: string | null;
}

export interface WorkbenchPreferences {
  version: 1;
  pinnedDatasetIds: number[];
  recent: WorkbenchVisit[];
}

let volatilePreferences: WorkbenchPreferences | null = null;

function validId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function emptyPreferences(): WorkbenchPreferences {
  return { version: 1, pinnedDatasetIds: [], recent: [] };
}

/** Store only the local browser's supported query parameters, never a navigation URL. */
export function sanitizeBrowseQuery(datasetId: number, query: string | URLSearchParams): string {
  const result = new URLSearchParams({ dataset: String(datasetId) });
  const raw = typeof query === "string" ? query : query.toString();
  if (raw.length > 16000 || /^[a-z][a-z\d+.-]*:/i.test(raw) || raw.startsWith("//")) return result.toString();
  let input = raw;
  if (input.startsWith("/")) {
    if (!input.startsWith("/browse?")) return result.toString();
    input = input.slice("/browse?".length);
  }
  const params = new URLSearchParams(input.replace(/^\?/, "").split("#", 1)[0]);
  for (const key of ["source", "q"]) {
    const value = params.get(key);
    if (value && value.length <= 4000 && !value.includes("\0")) result.set(key, value);
  }
  const folder = (params.get("folder") ?? "").replace(/\\/g, "/");
  if (folder && folder.length <= 4000 && !folder.startsWith("/") && !/^[a-z]:/i.test(folder) && !folder.includes("\0") && !folder.split("/").some((part) => part === "." || part === "..")) result.set("folder", folder);
  for (const key of ["page", "folderPage", "category", "batch"]) {
    const value = Number(params.get(key));
    if (validId(value) && (value > 1 || key === "category" || key === "batch")) result.set(key, String(value));
  }
  if (params.get("recursive") === "1") result.set("recursive", "1");
  if (params.get("type") === "all") result.set("type", "all");
  if (["small", "large"].includes(params.get("size") ?? "")) result.set("size", params.get("size")!);
  return result.toString();
}

function normalizePreferences(value: unknown): WorkbenchPreferences {
  if (!value || typeof value !== "object" || Array.isArray(value)) return emptyPreferences();
  const source = value as Record<string, unknown>;
  if (source.version !== 1) return emptyPreferences();
  const pinned = Array.isArray(source.pinnedDatasetIds) ? source.pinnedDatasetIds.filter(validId) : [];
  const recent: WorkbenchVisit[] = [];
  if (Array.isArray(source.recent)) {
    for (const item of source.recent) {
      if (!item || typeof item !== "object" || Array.isArray(item)) continue;
      const visit = item as Record<string, unknown>;
      if (!validId(visit.datasetId) || typeof visit.openedAt !== "number" || !Number.isFinite(visit.openedAt) || visit.openedAt <= 0 || visit.openedAt > Date.now() + 86400000) continue;
      recent.push({ datasetId: visit.datasetId, openedAt: visit.openedAt, browseQuery: typeof visit.browseQuery === "string" ? sanitizeBrowseQuery(visit.datasetId, visit.browseQuery) : null });
    }
  }
  recent.sort((a, b) => b.openedAt - a.openedAt);
  return { version: 1, pinnedDatasetIds: [...new Set(pinned)].slice(0, MAX_PINNED_DATASETS), recent: recent.filter((visit, index) => recent.findIndex((other) => other.datasetId === visit.datasetId) === index).slice(0, MAX_RECENT_DATASETS) };
}

export function readWorkbenchPreferences(): WorkbenchPreferences {
  if (volatilePreferences) return normalizePreferences(volatilePreferences);
  try { return normalizePreferences(JSON.parse(localStorage.getItem(WORKBENCH_STORAGE_KEY) ?? "null")); }
  catch { return emptyPreferences(); }
}

function writePreferences(preferences: WorkbenchPreferences) {
  try { localStorage.setItem(WORKBENCH_STORAGE_KEY, JSON.stringify(preferences)); volatilePreferences = null; }
  catch { volatilePreferences = preferences; }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function readLegacyLocations(): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(LEGACY_BROWSE_STORAGE_KEY) ?? "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  } catch { return {}; }
}

export function getRememberedBrowseLocation(datasetId: number, preferences = readWorkbenchPreferences()): URLSearchParams {
  const query = preferences.recent.find((visit) => visit.datasetId === datasetId)?.browseQuery;
  const legacy = readLegacyLocations()[String(datasetId)];
  return new URLSearchParams(sanitizeBrowseQuery(datasetId, query ?? (typeof legacy === "string" ? legacy : "")));
}

export function getContinueBrowseUrl(datasetId: number, preferences = readWorkbenchPreferences()): string {
  return `/browse?${getRememberedBrowseLocation(datasetId, preferences).toString()}`;
}

/** A detail visit changes recency without replacing a previously verified browser location. */
export function rememberDatasetVisit(datasetId: number, browseQuery?: string | URLSearchParams): void {
  if (!validId(datasetId)) return;
  const preferences = readWorkbenchPreferences();
  const previous = preferences.recent.find((visit) => visit.datasetId === datasetId);
  const legacy = readLegacyLocations()[String(datasetId)];
  const query = browseQuery === undefined ? previous?.browseQuery ?? (typeof legacy === "string" ? sanitizeBrowseQuery(datasetId, legacy) : null) : sanitizeBrowseQuery(datasetId, browseQuery);
  const visit = { datasetId, openedAt: Date.now(), browseQuery: query };
  writePreferences({ ...preferences, recent: [visit, ...preferences.recent.filter((item) => item.datasetId !== datasetId)].slice(0, MAX_RECENT_DATASETS) });
  if (browseQuery !== undefined) {
    try { sessionStorage.setItem(LEGACY_BROWSE_STORAGE_KEY, JSON.stringify({ ...readLegacyLocations(), [datasetId]: query })); }
    catch { /* Browser preferences are optional; browsing remains available. */ }
  }
}

export function togglePinnedDataset(datasetId: number): { pinned: boolean; limitReached: boolean } {
  const preferences = readWorkbenchPreferences();
  const pinned = preferences.pinnedDatasetIds.includes(datasetId);
  if (!validId(datasetId) || (!pinned && preferences.pinnedDatasetIds.length >= MAX_PINNED_DATASETS)) return { pinned: false, limitReached: true };
  writePreferences({ ...preferences, pinnedDatasetIds: pinned ? preferences.pinnedDatasetIds.filter((id) => id !== datasetId) : [...preferences.pinnedDatasetIds, datasetId] });
  return { pinned: !pinned, limitReached: false };
}

export function pruneWorkbenchPreferences(validIds: number[]): void {
  const valid = new Set(validIds);
  const previous = readWorkbenchPreferences();
  const next = { ...previous, pinnedDatasetIds: previous.pinnedDatasetIds.filter((id) => valid.has(id)), recent: previous.recent.filter((visit) => valid.has(visit.datasetId)) };
  if (JSON.stringify(next) !== JSON.stringify(previous)) writePreferences(next);
  try {
    const legacy = readLegacyLocations();
    const clean = Object.fromEntries(Object.entries(legacy).filter(([key]) => valid.has(Number(key))));
    if (Object.keys(clean).length !== Object.keys(legacy).length) sessionStorage.setItem(LEGACY_BROWSE_STORAGE_KEY, JSON.stringify(clean));
  } catch { /* Stale browser preferences never block the dataset list. */ }
}

export function subscribeWorkbenchPreferences(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== WORKBENCH_STORAGE_KEY && event.key !== null) return;
    volatilePreferences = null;
    onChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => { window.removeEventListener("storage", onStorage); window.removeEventListener(CHANGE_EVENT, onChange); };
}
