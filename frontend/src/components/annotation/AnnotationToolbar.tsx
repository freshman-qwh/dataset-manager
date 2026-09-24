import { Brush, CircleDot, Hand, Menu, MousePointer2, RotateCcw, RotateCw, Square, Waypoints, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { AnnotationShapeType } from "../../types/dataset";

export type AnnotationTool = "select" | "pan" | "brush" | AnnotationShapeType;
type Preset = "detection" | "segmentation" | "custom";
type ToolInfo = { id: AnnotationTool; title: string; shortcut?: string; icon: ReactNode };

interface Props {
  datasetId: number;
  taskType: string;
  tool: AnnotationTool;
  allowedShapeTypes: AnnotationShapeType[];
  canUndo: boolean;
  canRedo: boolean;
  onToolChange: (tool: AnnotationTool) => void;
  onUndo: () => void;
  onRedo: () => void;
}

const tools: ToolInfo[] = [
  { id: "select", title: "选择", shortcut: "V", icon: <MousePointer2 size={18} /> },
  { id: "rectangle", title: "矩形", shortcut: "R", icon: <Square size={18} /> },
  { id: "polygon", title: "多边形", shortcut: "P", icon: <Waypoints size={18} /> },
  { id: "brush", title: "画笔", shortcut: "B", icon: <Brush size={18} /> },
  { id: "point", title: "点", icon: <CircleDot size={18} /> },
  { id: "pan", title: "平移", shortcut: "H", icon: <Hand size={18} /> }
];
const presets: Record<Exclude<Preset, "custom">, AnnotationTool[]> = {
  detection: ["select", "rectangle", "pan"],
  segmentation: ["select", "polygon", "brush", "pan"]
};

function supported(id: AnnotationTool, allowed: AnnotationShapeType[]): boolean {
  return id === "select" || id === "pan" || (id === "brush" ? allowed.includes("polygon") : allowed.includes(id as AnnotationShapeType));
}

function readSettings(key: string, taskType: string): { preset: Preset; order: AnnotationTool[] } {
  const fallback: Exclude<Preset, "custom"> = taskType === "segmentation" ? "segmentation" : "detection";
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "null") as { preset?: string; order?: string[] } | null;
    const preset: Preset = value?.preset === "custom" || (value?.preset === taskType && (taskType === "detection" || taskType === "segmentation"))
      ? value.preset as Preset : fallback;
    const order = Array.isArray(value?.order)
      ? [...new Set(value.order.filter((id): id is AnnotationTool => tools.some((item) => item.id === id)))]
      : presets[fallback];
    const customOrder = order.length ? order : presets[fallback];
    return { preset, order: customOrder.includes("select") ? customOrder : ["select", ...customOrder] };
  } catch {
    return { preset: fallback, order: presets[fallback] };
  }
}

export default function AnnotationToolbar({
  datasetId, taskType, tool, allowedShapeTypes,
  canUndo, canRedo, onToolChange, onUndo, onRedo
}: Props) {
  const key = `dataset-manager:annotation-toolbar:${datasetId}:${taskType}`;
  const [settings, setSettings] = useState(() => readSettings(key, taskType));
  const [settingsKey, setSettingsKey] = useState(key);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    setSettingsKey(key);
    setSettings(readSettings(key, taskType));
  }, [key, taskType]);
  useEffect(() => {
    if (settingsKey !== key) return;
    try { localStorage.setItem(key, JSON.stringify(settings)); } catch { /* Optional local preference. */ }
  }, [key, settings, settingsKey]);
  const visible = useMemo(() => {
    const order = settings.preset === "custom" ? settings.order : presets[settings.preset];
    return [...new Set([...order, tool])]
      .filter((id) => supported(id, allowedShapeTypes))
      .map((id) => tools.find((item) => item.id === id)!);
  }, [settings, tool, allowedShapeTypes]);
  const activeOrder = settings.preset === "custom" ? settings.order : presets[settings.preset];
  const selectedTools = activeOrder.filter((id) => supported(id, allowedShapeTypes))
    .map((id) => tools.find((item) => item.id === id)!);
  const availableTools = tools.filter((item) => !settings.order.includes(item.id));
  const temporaryTool = !activeOrder.includes(tool) ? tools.find((item) => item.id === tool) : null;

  function add(id: AnnotationTool) {
    setSettings((current) => ({
      preset: "custom",
      order: current.order.includes(id) ? current.order : [...current.order, id]
    }));
  }
  function remove(id: AnnotationTool) {
    if (id === "select" || id === tool) return;
    setSettings((current) => ({ ...current, order: current.order.filter((item) => item !== id) }));
  }
  function move(id: AnnotationTool, delta: number) {
    setSettings((current) => {
      const order = [...current.order];
      const index = order.indexOf(id);
      const next = index + delta;
      if (next < 0 || next >= order.length) return current;
      [order[index], order[next]] = [order[next], order[index]];
      return { preset: "custom", order };
    });
  }

  return (
    <aside className="flex w-full shrink-0 flex-row items-center gap-2 border-b border-line bg-white p-2 lg:w-16 lg:flex-col lg:gap-3 lg:border-b-0 lg:border-r lg:p-3">
      <div className="flex gap-2 lg:flex-col lg:items-center">
        {visible.map((item) => (
          <button key={item.id} type="button"
            title={`${item.title}${item.shortcut ? ` (${item.shortcut})` : ""}`}
            aria-label={`${item.title}${item.shortcut ? `，快捷键 ${item.shortcut}` : ""}`}
            aria-pressed={tool === item.id} onClick={(event) => {
              onToolChange(item.id);
              if (event.detail > 0) event.currentTarget.blur();
            }}
            className={`inline-flex h-11 w-11 items-center justify-center rounded-lg border transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 ${tool === item.id ? "border-gray-900 bg-gray-900 text-white" : "border-line bg-white text-gray-600 hover:bg-gray-50"}`}
          >{item.icon}</button>
        ))}
      </div>
      <div className="h-8 w-px bg-line lg:h-px lg:w-full" />
      <div className="flex gap-2 lg:flex-col lg:items-center">
        <button type="button" title="撤销 (Ctrl+Z)" aria-label="撤销，快捷键 Ctrl+Z" onClick={onUndo} disabled={!canUndo}
          className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"><RotateCcw size={18} /></button>
        <button type="button" title="重做 (Ctrl+Y)" aria-label="重做，快捷键 Ctrl+Y" onClick={onRedo} disabled={!canRedo}
          className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"><RotateCw size={18} /></button>
      </div>
      <button type="button" title="配置标注工具栏" aria-label="配置标注工具栏" onClick={() => setOpen(true)}
        className="ml-auto inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-gray-600 hover:bg-gray-50 lg:ml-0 lg:mt-auto"><Menu size={19} /></button>

      {open && <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4"
        onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
        <div role="dialog" aria-modal="true" aria-label="配置标注工具栏"
          onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false); } }}
          className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-xl">
          <div className="flex items-start justify-between border-b border-line px-6 py-5">
            <div><h2 className="text-lg font-semibold text-ink">配置标注工具栏</h2>
              <p className="mt-1 text-sm text-gray-500">选择任务预设，或自定义工具与顺序。</p></div>
            <button type="button" aria-label="关闭工具栏配置" onClick={() => setOpen(false)} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"><X size={18} /></button>
          </div>
          <div className="overflow-y-auto px-6 py-5">
            <div className="grid gap-3 sm:grid-cols-3">
              {(["detection", "segmentation", "custom"] as const).map((preset) => {
                const enabled = preset === "custom" || preset === taskType;
                const title = preset === "detection" ? "目标检测" : preset === "segmentation" ? "实例分割" : "自定义";
                const description = preset === "detection" ? "选择 · 矩形 · 平移" : preset === "segmentation" ? "选择 · 多边形 · 画笔 · 平移" : `独立保存 ${settings.order.length} 项工具及顺序`;
                return <button key={preset} type="button" disabled={!enabled} aria-pressed={settings.preset === preset}
                  onClick={() => setSettings((current) => ({ ...current, preset }))}
                  className={`rounded-xl border p-4 text-left ${settings.preset === preset ? "border-gray-900 bg-gray-50" : "border-line"} ${enabled ? "hover:border-gray-500" : "cursor-not-allowed opacity-50"}`}>
                  <span className="text-sm font-semibold text-ink">{title}</span>
                  <span className="mt-2 block text-xs leading-5 text-gray-500">{description}</span>
                  {!enabled && <span className="mt-1 block text-xs text-gray-400">当前数据集不可应用</span>}
                </button>;
              })}
            </div>
            <h3 className="mt-6 text-sm font-semibold text-ink">{settings.preset === "custom" ? "自定义工具顺序" : "当前预设工具"}</h3>
            <p className="mt-1 text-xs text-gray-500">{settings.preset === "custom"
              ? "从上到下为工具栏顺序；自定义方案会单独保留。当前使用的工具不能移除。"
              : "预设顺序固定；切回自定义时会恢复上次选择和排序。"}</p>
            <ol className="mt-3 space-y-2">
              {selectedTools.map((item, index) => (
                <li key={item.id} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gray-100 text-xs font-semibold tabular-nums text-gray-700" aria-label={`第 ${index + 1} 位`}>{index + 1}</span>
                  <span className="text-gray-600">{item.icon}</span>
                  <span className="min-w-0 flex-1 text-sm text-ink">{item.title}</span>
                  {settings.preset === "custom" && <>
                    <button type="button" aria-label={`${item.title}上移`} disabled={index === 0}
                      onClick={() => move(item.id, -1)} className="rounded px-2 py-1 text-sm hover:bg-gray-100 disabled:text-gray-300 disabled:hover:bg-transparent">↑</button>
                    <button type="button" aria-label={`${item.title}下移`} disabled={index === selectedTools.length - 1}
                      onClick={() => move(item.id, 1)} className="rounded px-2 py-1 text-sm hover:bg-gray-100 disabled:text-gray-300 disabled:hover:bg-transparent">↓</button>
                    <button type="button" aria-label={`移除${item.title}`} disabled={item.id === "select" || item.id === tool}
                      onClick={() => remove(item.id)} className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 disabled:text-gray-300 disabled:hover:bg-transparent">移除</button>
                  </>}
                </li>
              ))}
            </ol>
            {temporaryTool && <p className="mt-2 text-xs text-gray-500">
              正在使用的“{temporaryTool.title}”会暂时留在工具栏；切换到已选工具后即隐藏。
            </p>}
            {settings.preset === "custom" && <>
              <h3 className="mt-6 text-sm font-semibold text-ink">可添加工具</h3>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {availableTools.map((item) => {
                  const enabled = supported(item.id, allowedShapeTypes);
                  return <div key={item.id} className={`flex items-center gap-2 rounded-lg border border-line px-3 py-2 ${enabled ? "" : "opacity-50"}`}>
                    <span className="text-gray-600">{item.icon}</span>
                    <span className="min-w-0 flex-1 text-sm text-ink">{item.title}</span>
                    <button type="button" aria-label={`添加${item.title}`} disabled={!enabled} onClick={() => add(item.id)}
                      className="rounded px-2 py-1 text-xs text-gray-700 hover:bg-gray-100 disabled:text-gray-400 disabled:hover:bg-transparent">{enabled ? "添加" : "当前不可用"}</button>
                  </div>;
                })}
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                {["橡皮擦", "边缘吸附", "智能辅助"].map((name) =>
                  <div key={name} className="flex items-center justify-between rounded-lg border border-dashed border-line bg-gray-50 px-3 py-2 text-xs text-gray-400">
                    {name}<span>规划中</span>
                  </div>
                )}
              </div>
            </>}
          </div>
          <div className="flex justify-end border-t border-line px-6 py-4">
            <button type="button" autoFocus onClick={() => setOpen(false)} className="rounded-lg bg-gray-900 px-5 py-2 text-sm font-medium text-white">完成</button>
          </div>
        </div>
      </div>}
    </aside>
  );
}
