import { Loader2 } from "lucide-react";
import type { useSamAssistance } from "./useSamAssistance";

export type SamMode = "positive" | "negative" | "box";

interface Props {
  sam: ReturnType<typeof useSamAssistance>;
  mode: SamMode;
  onModeChange: (mode: SamMode) => void;
  onAccept: () => void;
  onRetry: () => void;
  onUndoPrompt: () => void;
}

export default function SamControls({ sam, mode, onModeChange, onAccept, onRetry, onUndoPrompt }: Props) {
  return <div aria-label="SAM 辅助分割" className="shrink-0 border-b border-line bg-white px-3 py-2 text-xs text-gray-600">
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-semibold text-gray-900">SAM 辅助</span>
      {([ ["positive", "包含点"], ["negative", "排除点"], ["box", "框选目标"] ] as const).map(([value, label]) =>
        <button key={value} type="button" aria-pressed={mode === value} disabled={sam.busy || !sam.status?.ready}
          onClick={() => onModeChange(value)} className={`min-h-11 rounded-md border lg:min-h-0 px-2 py-1.5 disabled:opacity-40 ${mode === value ? "border-gray-900 bg-gray-900 text-white" : "border-line hover:bg-gray-50"}`}>{label}</button>)}
      <button type="button" disabled={sam.busy || !sam.prompts.points.length} onClick={onUndoPrompt}
        className="min-h-11 rounded-md border lg:min-h-0 border-line px-2 py-1.5 hover:bg-gray-50 disabled:opacity-40">撤回提示点</button>
      <button type="button" disabled={!sam.hasDraft} onClick={sam.reset}
        className="min-h-11 rounded-md border lg:min-h-0 border-line px-2 py-1.5 hover:bg-gray-50 disabled:opacity-40">重新开始</button>
      <button type="button" disabled={!sam.canCommit} onClick={onAccept}
        className="min-h-11 rounded-md bg-gray-900 lg:min-h-0 px-3 py-1.5 font-medium text-white disabled:bg-gray-300">确认轮廓并精修</button>
    </div>
    <div role="status" aria-live="polite" className="mt-1.5 flex flex-wrap items-center gap-2 leading-5">
      {sam.checking ? <span>正在检查模型…</span> : sam.busy ? <>
        <Loader2 size={13} className="animate-spin" /><span>正在生成轮廓，首次分析图片可能较慢…</span>
      </> : sam.error ? <><span className="text-red-700">{sam.error}</span>
        <button type="button" onClick={sam.status?.ready && sam.hasDraft ? onRetry : () => void sam.refreshStatus()} className="underline">重试</button></>
        : !sam.status?.ready ? <><span>{sam.status?.message ?? "模型状态暂不可用"}</span>
          <button type="button" onClick={() => void sam.refreshStatus()} className="underline">重新检查</button></>
        : <span>{mode === "box" ? "拖框圈住目标；新框会替换当前提示。" : "点击包含／排除区域，可继续加点修正。"} 确认后可拖动顶点，再保存标注。
          {sam.prediction && ` ${sam.prediction.polygons.length} 个轮廓 · ${(sam.prediction.elapsed_ms / 1000).toFixed(1)} 秒 · ${sam.prediction.device === "cuda" ? "GPU" : "CPU"}`}</span>}
    </div>
    {sam.prediction?.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-700">{warning}</p>)}
  </div>;
}
