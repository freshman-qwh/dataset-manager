import { Download, Filter, RefreshCw, Search, Tags, Upload } from "lucide-react";

interface SearchFilterBarProps {
  search: string;
  fileType: string;
  tag: string;
  split: string;
  exportFormat: string;
  onSearchChange: (value: string) => void;
  onFileTypeChange: (value: string) => void;
  onTagChange: (value: string) => void;
  onSplitChange: (value: string) => void;
  onExportFormatChange: (value: string) => void;
  onScan: () => void;
  onImportMetadata: () => void;
  onManageTags: () => void;
  onExport: () => void;
}

export default function SearchFilterBar({
  search,
  fileType,
  tag,
  split,
  exportFormat,
  onSearchChange,
  onFileTypeChange,
  onTagChange,
  onSplitChange,
  onExportFormatChange,
  onScan,
  onImportMetadata,
  onManageTags,
  onExport
}: SearchFilterBarProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-white p-3 shadow-sm lg:flex-row lg:items-center">
      <div className="relative min-w-0 flex-1">
        <Search className="pointer-events-none absolute left-3 top-2.5 text-gray-400" size={18} />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          className="w-full rounded-lg border border-line py-2 pl-10 pr-3 text-sm outline-none transition focus:border-gray-900"
          placeholder="搜索文件名、路径、hash"
        />
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="relative">
          <Filter className="pointer-events-none absolute left-3 top-2.5 text-gray-400" size={17} />
          <select
            value={fileType}
            onChange={(event) => onFileTypeChange(event.target.value)}
            className="w-full rounded-lg border border-line bg-white py-2 pl-10 pr-8 text-sm outline-none transition focus:border-gray-900 sm:w-36"
          >
            <option value="">全部类型</option>
            <option value="image">图片</option>
            <option value="video">视频</option>
            <option value="table">CSV</option>
          </select>
        </label>
        <input
          value={tag}
          onChange={(event) => onTagChange(event.target.value)}
          className="w-full rounded-lg border border-line px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-36"
          placeholder="标签筛选"
        />
        <select
          value={split}
          onChange={(event) => onSplitChange(event.target.value)}
          className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
        >
          <option value="">全部划分</option>
          <option value="train">train</option>
          <option value="val">val</option>
          <option value="test">test</option>
          <option value="unassigned">未划分</option>
        </select>
        <button
          type="button"
          title="扫描"
          onClick={onScan}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <RefreshCw size={17} />
          扫描
        </button>
        <button
          type="button"
          title="标签体系"
          onClick={onManageTags}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <Tags size={17} />
          标签
        </button>
        <button
          type="button"
          title="导入元数据"
          onClick={onImportMetadata}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <Upload size={17} />
          导入
        </button>
        <select
          value={exportFormat}
          onChange={(event) => onExportFormatChange(event.target.value)}
          className="rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
        >
          <option value="manifest">manifest</option>
          <option value="csv">CSV 标签表</option>
          <option value="coco">COCO 骨架</option>
          <option value="yolo">YOLO 骨架</option>
        </select>
        <button
          type="button"
          title="导出"
          onClick={onExport}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
        >
          <Download size={17} />
          导出
        </button>
      </div>
    </div>
  );
}
