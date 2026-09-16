import { Filter, RotateCcw, Search } from "lucide-react";

import { annotationProgressCopy, reviewStatusCopy, uiCopy } from "../utils/uiCopy";

interface SearchFilterBarProps {
  search: string;
  fileType: string;
  fileStatus: string;
  tag: string;
  split: string;
  reviewStatus: string;
  annotationProgress: string;
  showAnnotationProgress?: boolean;
  onSearchChange: (value: string) => void;
  onFileTypeChange: (value: string) => void;
  onFileStatusChange: (value: string) => void;
  onTagChange: (value: string) => void;
  onSplitChange: (value: string) => void;
  onReviewStatusChange: (value: string) => void;
  onAnnotationProgressChange: (value: string) => void;
  onClear: () => void;
}

export default function SearchFilterBar({
  search,
  fileType,
  fileStatus,
  tag,
  split,
  reviewStatus,
  annotationProgress,
  showAnnotationProgress = true,
  onSearchChange,
  onFileTypeChange,
  onFileStatusChange,
  onTagChange,
  onSplitChange,
  onReviewStatusChange,
  onAnnotationProgressChange,
  onClear
}: SearchFilterBarProps) {
  const tagValue = tag === "__untagged__" ? uiCopy.noSampleTags : tag === "__tagged__" ? "有标签" : tag;
  const hasFilters = Boolean(search || fileType || fileStatus || tag || split || reviewStatus || annotationProgress);

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
          onChange={(event) => {
            const value = event.target.value.trim();
            onTagChange(value === uiCopy.noSampleTags ? "__untagged__" : value === "有标签" ? "__tagged__" : event.target.value);
          }}
          className="w-full rounded-lg border border-line px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
          placeholder={`${uiCopy.sampleTags} / ${uiCopy.noSampleTags}`}
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
        {showAnnotationProgress && (
          <select
            value={annotationProgress}
            onChange={(event) => onAnnotationProgressChange(event.target.value)}
            className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
          >
            <option value="">全部{uiCopy.annotationProgress}</option>
            <option value="not_started">{annotationProgressCopy.not_started}</option>
            <option value="in_progress">{annotationProgressCopy.in_progress}</option>
            <option value="completed_empty">{annotationProgressCopy.completed_empty}</option>
            <option value="completed_with_objects">{annotationProgressCopy.completed_with_objects}</option>
          </select>
        )}
        <select
          value={reviewStatus}
          onChange={(event) => onReviewStatusChange(event.target.value)}
          className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900 sm:w-32"
        >
          <option value="">全部{uiCopy.reviewStatus}</option>
          <option value="not_reviewed">{reviewStatusCopy.not_reviewed}</option>
          <option value="in_review">{reviewStatusCopy.in_review}</option>
          <option value="approved">{reviewStatusCopy.approved}</option>
          <option value="rejected">{reviewStatusCopy.rejected}</option>
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
