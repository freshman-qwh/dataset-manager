import type { AnnotationQueueScope } from "../types/dataset";

const QUEUE_STATE_KEY_PREFIX = "dataset-manager.annotation.queue.";
const QUEUE_QUERY_KEYS = [
  "queue",
  "search",
  "fileStatus",
  "tag",
  "split",
  "queueSplit",
  "reviewStatus",
  "annotationProgress",
  "sortBy",
  "sortOrder"
] as const;

export const annotationQueueCopy: Record<AnnotationQueueScope, string> = {
  all_pending: "全部待处理",
  current_filter: "当前筛选",
  current_split: "当前划分"
};

export interface StoredAnnotationQueue {
  sampleId: number;
  query: string;
  updatedAt: string;
  version?: number;
}

function storageKey(datasetId: number): string {
  return `${QUEUE_STATE_KEY_PREFIX}${datasetId}`;
}

export function readAnnotationQueue(datasetId: number): StoredAnnotationQueue | null {
  try {
    const raw = window.localStorage.getItem(storageKey(datasetId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<StoredAnnotationQueue>;
    if (!Number.isFinite(parsed.sampleId) || typeof parsed.query !== "string" || typeof parsed.updatedAt !== "string") {
      return null;
    }
    const query = new URLSearchParams(parsed.query);
    if (query.get("queue") === "current_split" && !query.get("queueSplit") && query.get("split")) {
      query.set("queueSplit", query.get("split") as string);
      query.delete("split");
      parsed.query = query.toString();
      parsed.version = 2;
      window.localStorage.setItem(storageKey(datasetId), JSON.stringify(parsed));
    }
    return parsed as StoredAnnotationQueue;
  } catch {
    return null;
  }
}

export function writeAnnotationQueue(datasetId: number, sampleId: number, source: URLSearchParams): void {
  try {
    const query = new URLSearchParams();
    for (const key of QUEUE_QUERY_KEYS) {
      const value = source.get(key);
      if (value) {
        query.set(key, value);
      }
    }
    query.set("sample", String(sampleId));
    query.set("resume", "1");
    window.localStorage.setItem(
      storageKey(datasetId),
      JSON.stringify({
        sampleId,
        query: query.toString(),
        updatedAt: new Date().toISOString(),
        version: 2
      } satisfies StoredAnnotationQueue)
    );
  } catch {
    // Queue recovery is a progressive enhancement; annotation remains usable without storage.
  }
}

export function buildDefaultPendingQueue(): string {
  return new URLSearchParams({
    queue: "all_pending",
    sortBy: "created_at",
    sortOrder: "asc",
    resume: "1"
  }).toString();
}

export function buildReviewQueue(stored: StoredAnnotationQueue | null): string {
  if (!stored) {
    return new URLSearchParams({
      queue: "current_filter",
      fileStatus: "normal",
      sortBy: "created_at",
      sortOrder: "asc",
      resume: "1"
    }).toString();
  }

  const query = new URLSearchParams(stored.query);
  const storedScope = query.get("queue");
  if (storedScope === "all_pending") {
    for (const key of ["search", "tag", "split", "queueSplit", "reviewStatus", "annotationProgress"]) {
      query.delete(key);
    }
    query.set("queue", "current_filter");
    query.set("fileStatus", "normal");
  } else if (storedScope === "current_split") {
    const queueSplit = query.get("queueSplit");
    for (const key of ["search", "tag", "queueSplit", "reviewStatus", "annotationProgress"]) {
      query.delete(key);
    }
    query.set("queue", "current_filter");
    query.set("fileStatus", "normal");
    if (queueSplit) {
      query.set("split", queueSplit);
    }
  } else {
    if (query.get("annotationProgress") === "not_started" || query.get("annotationProgress") === "in_progress") {
      query.delete("annotationProgress");
    }
    if (query.get("reviewStatus") === "not_reviewed") {
      query.delete("reviewStatus");
    }
  }
  query.set("sample", String(stored.sampleId));
  query.set("resume", "1");
  return query.toString();
}

export function buildQueueChangeParams(
  source: URLSearchParams,
  nextScope: AnnotationQueueScope,
  currentSplit: string | null | undefined
): URLSearchParams {
  const next = new URLSearchParams(source);
  next.set("queue", nextScope);
  next.set("resume", "1");
  next.delete("sample");
  next.delete("annotation");
  if (nextScope === "current_split") {
    next.set("queueSplit", currentSplit || "unassigned");
  } else {
    next.delete("queueSplit");
  }
  return next;
}
