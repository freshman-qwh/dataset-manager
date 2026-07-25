import { CircleDot, Hand, MousePointer2, RotateCcw, RotateCw, Square, Waypoints } from "lucide-react";
import type { ReactNode } from "react";

import type { AnnotationShapeType } from "../../types/dataset";

export type AnnotationTool = "select" | "pan" | AnnotationShapeType;

interface AnnotationToolbarProps {
  tool: AnnotationTool;
  allowedShapeTypes: AnnotationShapeType[];
  canUndo: boolean;
  canRedo: boolean;
  onToolChange: (tool: AnnotationTool) => void;
  onUndo: () => void;
  onRedo: () => void;
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
  allowedShapeTypes,
  canUndo,
  canRedo,
  onToolChange,
  onUndo,
  onRedo
}: AnnotationToolbarProps) {
  const visibleTools = tools.filter(
    (item) => item.id === "select" || item.id === "pan" || allowedShapeTypes.includes(item.id as AnnotationShapeType)
  );

  return (
    <aside className="flex w-full shrink-0 flex-row items-center gap-2 border-b border-line bg-white p-2 lg:w-16 lg:flex-col lg:gap-3 lg:border-b-0 lg:border-r lg:p-3">
      <div className="flex gap-2 lg:flex-col lg:items-center">
        {visibleTools.map((item) => (
          <button
            key={item.id}
            type="button"
            title={item.title}
            aria-pressed={tool === item.id}
            onClick={() => onToolChange(item.id)}
            className={`inline-flex h-11 w-11 items-center justify-center rounded-lg border text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 ${
              tool === item.id
                ? "border-gray-900 bg-gray-900 text-white"
                : "border-line bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            {item.icon}
          </button>
        ))}
      </div>
      <div className="h-8 w-px bg-line lg:h-px lg:w-full" />
      <div className="flex gap-2 lg:flex-col lg:items-center">
        <button
          type="button"
          title="撤销"
          onClick={onUndo}
          disabled={!canUndo}
          className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-gray-600 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 disabled:cursor-not-allowed disabled:text-gray-300"
        >
          <RotateCcw size={18} />
        </button>
        <button
          type="button"
          title="重做"
          onClick={onRedo}
          disabled={!canRedo}
          className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line text-gray-600 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 disabled:cursor-not-allowed disabled:text-gray-300"
        >
          <RotateCw size={18} />
        </button>
      </div>
    </aside>
  );
}
