import { Filter, RotateCcw, Search } from "lucide-react";

interface SearchFilterBarProps {
  search: string;
  fileType: string;
  fileStatus: string;
  tag: string;
  split: string;
  reviewStatus: string;
  annotationStatus: string;
  onSearchChange: (value: string) => void;
  onFileTypeChange: (value: string) => void;
  onFileStatusChange: (value: string) => void;
  onTagChange: (value: string) => void;
  onSplitChange: (value: string) => void;
  onReviewStatusChange: (value: string) => void;
  onAnnotationStatusChange: (value: string) => void;
  onClear: () => void;
}

export default function SearchFilterBar({
  search,
  fileType,
  fileStatus,
  tag,
  split,
  reviewStatus,
  annotationStatus,
  onSearchChange,
  onFileTypeChange,
  onFileStatusChange,
  onTagChange,
  onSplitChange,
  onReviewStatusChange,
  onAnnotationStatusChange,
  onClear
}: SearchFilterBarProps) {
  const tagValue = tag === "__untagged__" ? "未标注" : tag;
  const hasFilters = Boolean(search || fileType || fileStatus || tag || split || reviewStatus || annotationStatus);

  return (
    <div className="grid gap-3 rounded-lg border border-line bg-white p-3 shadow-sm xl:grid-cols-[minmax(240px,1fr)_auto]">
      <div className="relative min-w-0 xl:max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-2.5 text-gray-400" size={18} />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          className="w-full rounded-lg border border-line py-2 pl-10 pr-3 text-sm outline-none transition focus:border-gray-900"
          placeholder="搜索文件名、路径、hash"
        />
      </div>
      <div className="flex flex-wrap gap-3 xl:justify-end">
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
          value={tagValue}
          onChange={(event) => onTagChange(event.target.value.trim() === "未标注" ? "__untagged__" : event.target.value)}
          className="w-full rounded-lg border border-line px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
          placeholder="标签筛选 / 未标注"
        />
        <select
          value={split}
          onChange={(event) => onSplitChange(event.target.value)}
          className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-28"
        >
          <option value="">全部划分</option>
          <option value="train">train</option>
          <option value="val">val</option>
          <option value="test">test</option>
          <option value="unassigned">未划分</option>
        </select>
        <select
          value={annotationStatus}
          onChange={(event) => onAnnotationStatusChange(event.target.value)}
          className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
        >
          <option value="">全部标注</option>
          <option value="empty">空标注</option>
          <option value="annotated">已有对象</option>
        </select>
        <select
          value={reviewStatus}
          onChange={(event) => onReviewStatusChange(event.target.value)}
          className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
        >
          <option value="">全部审查</option>
          <option value="unlabeled">未标注</option>
          <option value="in_review">待审核</option>
          <option value="approved">已通过</option>
          <option value="rejected">已拒绝</option>
        </select>
        <select
          value={fileStatus}
          onChange={(event) => onFileStatusChange(event.target.value)}
          className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-28"
        >
          <option value="">全部状态</option>
          <option value="normal">正常</option>
          <option value="missing">缺失</option>
          <option value="permission_denied">无权限</option>
          <option value="duplicate">重复</option>
        </select>
        <button
          type="button"
          title="清空筛选"
          onClick={onClear}
          disabled={!hasFilters}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
        >
          <RotateCcw size={16} />
          清空
        </button>
      </div>
    </div>
  );
}
