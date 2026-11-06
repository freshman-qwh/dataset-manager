import { Download, MoreHorizontal, Tags, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { uiCopy } from "../utils/uiCopy";

interface DatasetActionMenuProps {
  exportFormat: string;
  onExportFormatChange: (value: string) => void;
  onManageTags: () => void;
  onImportMetadata: () => void;
  onImportLabelme: () => void;
  onExport: () => void;
  onAnnotationExport: () => void;
  annotationExportEnabled?: boolean;
  annotationImportEnabled?: boolean;
  annotationExportHint?: string;
}

export default function DatasetActionMenu({
  exportFormat,
  onExportFormatChange,
  onManageTags,
  onImportMetadata,
  onImportLabelme,
  onExport,
  onAnnotationExport,
  annotationExportEnabled = true,
  annotationImportEnabled = true,
  annotationExportHint
}: DatasetActionMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) setOpen(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
      }
    }
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  function closeAfter(action: () => void) {
    action();
    setOpen(false);
  }

  return (
    <div ref={menuRef} className="relative w-full sm:w-auto">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        <MoreHorizontal size={17} />
        其他操作
      </button>
      {open && (
        <div className="absolute left-0 z-20 mt-2 w-full rounded-lg border border-line bg-white p-2 shadow-soft sm:left-auto sm:right-0 sm:w-64">
          <button
            type="button"
            onClick={() => closeAfter(onManageTags)}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
          >
            <Tags size={16} />
            管理{uiCopy.sampleTags}
          </button>
          <button
            type="button"
            onClick={() => closeAfter(onImportMetadata)}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
          >
            <Upload size={16} />
            导入元数据
          </button>
          {annotationImportEnabled && <button
            type="button"
            onClick={() => closeAfter(onImportLabelme)}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
          >
            <Upload size={16} />
            导入标注
          </button>}
          <div className="my-2 border-t border-line" />
          <label className="block px-3 text-xs font-medium text-gray-500">元数据导出格式</label>
          <select
            aria-label="元数据导出格式"
            value={exportFormat}
            onChange={(event) => onExportFormatChange(event.target.value)}
            className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900"
          >
            <option value="manifest">Manifest 审计清单（JSON）</option>
            <option value="csv">CSV 标签表</option>
          </select>
          <button
            type="button"
            onClick={() => closeAfter(onExport)}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            <Download size={16} />
            导出元数据
          </button>
          {annotationExportEnabled && <button
            type="button"
            onClick={() => closeAfter(onAnnotationExport)}
            title={annotationExportHint}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-300"
          >
            <Download size={16} />
            标注训练格式
          </button>}
        </div>
      )}
    </div>
  );
}
