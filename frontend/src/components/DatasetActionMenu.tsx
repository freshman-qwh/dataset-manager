import { Download, MoreHorizontal, RefreshCw, Tags, Upload } from "lucide-react";
import { useState } from "react";

import { uiCopy } from "../utils/uiCopy";

interface DatasetActionMenuProps {
  exportFormat: string;
  onExportFormatChange: (value: string) => void;
  onManageTags: () => void;
  onScan: () => void;
  onImportMetadata: () => void;
  onExport: () => void;
  onAnnotationExport: () => void;
  annotationExportEnabled?: boolean;
  annotationExportHint?: string;
  scanning?: boolean;
}

export default function DatasetActionMenu({
  exportFormat,
  onExportFormatChange,
  onManageTags,
  onScan,
  onImportMetadata,
  onExport,
  onAnnotationExport,
  annotationExportEnabled = true,
  annotationExportHint,
  scanning = false
}: DatasetActionMenuProps) {
  const [open, setOpen] = useState(false);

  function closeAfter(action: () => void) {
    action();
    setOpen(false);
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        <MoreHorizontal size={17} />
        其他操作
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-64 rounded-lg border border-line bg-white p-2 shadow-soft">
          <button
            type="button"
            onClick={() => closeAfter(onScan)}
            disabled={scanning}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
          >
            <RefreshCw size={16} className={scanning ? "animate-spin" : ""} />
            {scanning ? "扫描任务运行中" : "更新扫描"}
          </button>
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
          <div className="my-2 border-t border-line" />
          <label className="block px-3 text-xs font-medium text-gray-500">导出格式</label>
          <select
            value={exportFormat}
            onChange={(event) => onExportFormatChange(event.target.value)}
            className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900"
          >
            <option value="manifest">manifest</option>
            <option value="csv">CSV 标签表</option>
          </select>
          <button
            type="button"
            onClick={() => closeAfter(onExport)}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            <Download size={16} />
            导出
          </button>
          <button
            type="button"
            onClick={() => closeAfter(onAnnotationExport)}
            disabled={!annotationExportEnabled}
            title={annotationExportHint}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-300"
          >
            <Download size={16} />
            标注训练格式
          </button>
        </div>
      )}
    </div>
  );
}
