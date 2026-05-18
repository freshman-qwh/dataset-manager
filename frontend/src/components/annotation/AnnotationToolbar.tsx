import { CircleDot, Hand, MousePointer2, RotateCcw, RotateCw, Save, Square, Trash2, Waypoints } from "lucide-react";
import type { ReactNode } from "react";

import type { AnnotationShapeType, Tag } from "../../types/dataset";

export type AnnotationTool = "select" | "pan" | AnnotationShapeType;

interface AnnotationToolbarProps {
  tool: AnnotationTool;
  label: string;
  tags: Tag[];
  dirty: boolean;
  saving: boolean;
  canUndo: boolean;
  canRedo: boolean;
  hasActiveObject: boolean;
  onToolChange: (tool: AnnotationTool) => void;
  onLabelChange: (label: string) => void;
  onSave: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onDeleteActive: () => void;
}

const tools: Array<{ id: AnnotationTool; title: string; icon: ReactNode }> = [
  { id: "select", title: "选择", icon: <MousePointer2 size={18} /> },
  { id: "rectangle", title: "矩形", icon: <Square size={18} /> },
  { id: "polygon", title: "多边形", icon: <Waypoints size={18} /> },
  { id: "point", title: "点", icon: <CircleDot size={18} /> },
  { id: "pan", title: "平移", icon: <Hand size={18} /> }
];

export default function AnnotationToolbar({
  tool,
  label,
  tags,
  dirty,
  saving,
  canUndo,
  canRedo,
  hasActiveObject,
  onToolChange,
  onLabelChange,
  onSave,
  onUndo,
  onRedo,
  onDeleteActive
}: AnnotationToolbarProps) {
  return (
    <aside className="flex w-full flex-col gap-3 border-b border-line bg-white p-3 lg:w-20 lg:border-b-0 lg:border-r">
      <div className="flex gap-2 lg:flex-col">
        {tools.map((item) => (
          <button
            key={item.id}
            type="button"
            title={item.title}
            onClick={() => onToolChange(item.id)}
            className={`inline-flex h-10 w-10 items-center justify-center rounded-lg border text-sm transition ${
              tool === item.id
                ? "border-gray-900 bg-gray-900 text-white"
                : "border-line bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            {item.icon}
          </button>
        ))}
      </div>
      <div className="h-px bg-line lg:w-full" />
      <div className="flex gap-2 lg:flex-col">
        <button
          type="button"
          title="撤销"
          onClick={onUndo}
          disabled={!canUndo}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
        >
          <RotateCcw size={18} />
        </button>
        <button
          type="button"
          title="重做"
          onClick={onRedo}
          disabled={!canRedo}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
        >
          <RotateCw size={18} />
        </button>
        <button
          type="button"
          title="删除当前对象"
          onClick={onDeleteActive}
          disabled={!hasActiveObject}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-red-200 text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-red-200"
        >
          <Trash2 size={18} />
        </button>
      </div>
      <div className="h-px bg-line lg:w-full" />
      <label className="min-w-48 flex-1 lg:min-w-0 lg:flex-none">
        <span className="sr-only">当前类别</span>
        <input
          value={label}
          list="annotation-label-options"
          onChange={(event) => onLabelChange(event.target.value)}
          className="h-10 w-full rounded-lg border border-line px-3 text-sm outline-none transition focus:border-gray-900 lg:w-14 lg:px-2"
          placeholder="类别"
        />
        <datalist id="annotation-label-options">
          {tags.map((tag) => (
            <option key={tag.id} value={tag.name} />
          ))}
        </datalist>
      </label>
      <button
        type="button"
        title="保存标注"
        onClick={onSave}
        disabled={saving || !dirty}
        className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300 lg:w-10 lg:px-0"
      >
        <Save size={18} />
        <span className="lg:sr-only">{saving ? "保存中" : dirty ? "保存" : "已保存"}</span>
      </button>
    </aside>
  );
}
