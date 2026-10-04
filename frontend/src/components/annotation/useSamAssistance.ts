import axios from "axios";
import { useCallback, useEffect, useRef, useState } from "react";

import { getSamStatus, predictSam } from "../../api/client";
import type { SamPrediction, SamPrompts, SamStatus } from "../../types/sam";

const emptyPrompts = (): SamPrompts => ({ points: [], box: null });

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (error.code === "ECONNABORTED") return "生成超时，请稍候重试；首次分析图片可能较慢。";
  }
  return "SAM 请求失败，请检查本地服务后重试。";
}

export function useSamAssistance(sampleId: number, enabled: boolean) {
  const [status, setStatus] = useState<SamStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prompts, setPrompts] = useState<SamPrompts>(emptyPrompts);
  const [prediction, setPrediction] = useState<SamPrediction | null>(null);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const busyRef = useRef(false);

  const reset = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    busyRef.current = false;
    setBusy(false);
    setPrompts(emptyPrompts());
    setPrediction(null);
    setError(null);
  }, []);

  const refreshStatus = useCallback(async (signal?: AbortSignal) => {
    setChecking(true);
    setError(null);
    try {
      const result = await getSamStatus(signal);
      if (!signal?.aborted) setStatus(result);
    } catch (failure) {
      if (!signal?.aborted) { setStatus(null); setError(errorMessage(failure)); }
    } finally {
      if (!signal?.aborted) setChecking(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const check = new AbortController();
    void refreshStatus(check.signal);
    return () => check.abort();
  }, [enabled, refreshStatus]);

  useEffect(() => {
    reset();
    return () => { generation.current += 1; controller.current?.abort(); };
  }, [sampleId, reset]);

  async function generate(next: SamPrompts, size: { width: number; height: number }) {
    if (busyRef.current || !status?.ready) return;
    if (next.points.length > 64) { setError("最多支持 64 个提示点，请确认当前轮廓或重新开始。"); return; }
    if (!next.box && !next.points.some((point) => point.label === 1)) {
      setError("请先添加包含点或框选目标，再添加排除点。");
      return;
    }
    const requestId = ++generation.current;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setPrompts(next);
    // An old contour must never be confirmable for a newer, failed prompt.
    setPrediction(null);
    try {
      const result = await predictSam(sampleId, next, size, request.signal);
      if (requestId === generation.current && !request.signal.aborted && result.sample_id === sampleId) {
        setPrediction(result);
      }
    } catch (failure) {
      if (requestId === generation.current && !request.signal.aborted) setError(errorMessage(failure));
    } finally {
      if (requestId === generation.current) { busyRef.current = false; setBusy(false); }
    }
  }

  return { status, checking, busy, error, prompts, prediction, generate, reset, refreshStatus,
    hasDraft: busy || prompts.points.length > 0 || prompts.box !== null,
    canCommit: !busy && Boolean(prediction?.polygons.length) };
}
