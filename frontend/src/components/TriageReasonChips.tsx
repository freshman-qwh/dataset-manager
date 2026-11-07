import { Plus, X } from "lucide-react";
import { useState } from "react";

const DEFAULT_REASONS = ["反光疑似缺陷", "轻微可接受", "需要补拍", "边界不清，待确认"];
const LIMIT = 12;

interface Props {
  storageKey: string;
  disabled?: boolean;
  onInsert: (reason: string) => void;
}

function loadReasons(key: string): { reasons: string[]; warning: string | null } {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return { reasons: DEFAULT_REASONS, warning: null };
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length > LIMIT || !parsed.every((item) => typeof item === "string" && item.trim().length > 0 && item.length <= 120)) {
      return { reasons: DEFAULT_REASONS, warning: "常用理由记录无法读取，本次使用默认短语。" };
    }
    return { reasons: [...new Set(parsed as string[])], warning: null };
  } catch {
    return { reasons: DEFAULT_REASONS, warning: "浏览器无法读取常用理由，本次使用默认短语。" };
  }
}

export default function TriageReasonChips({ storageKey, disabled = false, onInsert }: Props) {
  const [initial] = useState(() => loadReasons(storageKey));
  const [reasons, setReasons] = useState(initial.reasons);
  const [warning, setWarning] = useState(initial.warning);
  const [custom, setCustom] = useState("");
  const [managing, setManaging] = useState(false);

  function persist(next: string[]) {
    setReasons(next);
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(next));
      setWarning(null);
    } catch {
      setWarning("常用理由未能保存到浏览器；本次仍可使用，重新打开后可能丢失。" );
    }
  }

  function add() {
    const value = custom.trim();
    if (!value || reasons.length >= LIMIT || reasons.includes(value)) return;
    persist([...reasons, value]);
    setCustom("");
  }

  return <section aria-label="常用判定理由" className="mt-2">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs text-gray-500">常用理由 · 点击追加到备注</span>
      <button type="button" onClick={() => setManaging((value) => !value)} className="rounded px-2 py-1 text-xs text-gray-600 underline underline-offset-2">{managing ? "完成管理" : "管理短语"}</button>
    </div>
    <div className="mt-1.5 flex flex-wrap gap-1.5">{reasons.map((reason) => <span key={reason} className="inline-flex min-w-0 max-w-full rounded-md border border-line bg-gray-50">
      <button type="button" disabled={disabled} onClick={() => onInsert(reason)} className="break-words px-2 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-100 disabled:opacity-40">{reason}</button>
      {managing && <button type="button" onClick={() => persist(reasons.filter((item) => item !== reason))} aria-label={`删除常用理由：${reason}`} className="shrink-0 px-1.5 text-gray-500 hover:text-red-700"><X size={13} /></button>}
    </span>)}</div>
    {managing && <div className="mt-2">
      <div className="flex min-w-0 gap-2"><input aria-label="新增常用理由" value={custom} onChange={(event) => setCustom(event.target.value)} maxLength={120} placeholder="新增短语，最多 120 字" className="min-w-0 flex-1 rounded-lg border border-line px-2 py-2 text-xs" /><button type="button" onClick={add} disabled={!custom.trim() || reasons.length >= LIMIT || reasons.includes(custom.trim())} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-line px-2 text-xs text-gray-700 disabled:opacity-40"><Plus size={13} />添加</button></div>
      <p className="mt-1 text-[11px] text-gray-400">{reasons.length}/{LIMIT} 条 · 保存在此浏览器中，不随数据库备份迁移。</p>
    </div>}
    {warning && <p role="status" className="mt-2 text-xs text-amber-800">{warning}</p>}
  </section>;
}
