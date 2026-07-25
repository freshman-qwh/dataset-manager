import { CheckCircle2, CircleSlash2, Eye, EyeOff, Lock, Plus, Save, Tags, Trash2, Unlock } from "lucide-react";

import type { AnnotationClass, AnnotationObject } from "../../types/dataset";
import { tagChipStyle } from "../../utils/colors";

interface AnnotationObjectListProps {
  objects: AnnotationObject[];
  activeObjectId: string | null;
  annotationClasses: AnnotationClass[];
  activeLabel: string;
  creatingClass: boolean;
  dirty: boolean;
  saving: boolean;
  draftActive: boolean;
  hasQueueContinuation: boolean;
  sampleAvailable: boolean;
  sampleCompleted: boolean;
  onSelect: (clientId: string) => void;
  onUpdate: (clientId: string, updates: Partial<AnnotationObject>) => void;
  onDelete: (clientId: string) => void;
  onActiveLabelChange: (label: string) => void;
  onCreateClass: () => void;
  onSaveDraft: () => void;
  onCompleteCurrent: () => void;
  onSaveAndNext: () => void;
  onSyncClassesToTags: () => void;
}

function objectTitle(object: AnnotationObject, index: number): string {
  return object.label || `对象 ${index + 1}`;
}

export default function AnnotationObjectList({
  objects,
  activeObjectId,
  annotationClasses,
  activeLabel,
  creatingClass,
  dirty,
  saving,
  draftActive,
  hasQueueContinuation,
  sampleAvailable,
  sampleCompleted,
  onSelect,
  onUpdate,
  onDelete,
  onActiveLabelChange,
  onCreateClass,
  onSaveDraft,
  onCompleteCurrent,
  onSaveAndNext,
  onSyncClassesToTags
}: AnnotationObjectListProps) {
  const classByName = new Map(annotationClasses.map((annotationClass) => [annotationClass.name.toLowerCase(), annotationClass]));
  const activeClass = classByName.get(activeLabel.trim().toLowerCase());
  const canCreateClass = Boolean(activeLabel.trim()) && !activeClass;
  const completedWithoutChanges = sampleCompleted && !dirty;
  const queueCompleted = completedWithoutChanges && !hasQueueContinuation;
  const completionLabel = completedWithoutChanges
    ? hasQueueContinuation ? "下一张" : "本队列已完成"
    : objects.length > 0
      ? hasQueueContinuation ? "完成并下一张" : "完成当前标注"
      : hasQueueContinuation ? "确认无目标并下一张" : "确认当前无目标";

  return (
    <aside className="flex h-80 min-h-0 w-full shrink-0 flex-col overflow-hidden border-t border-line bg-white lg:h-auto lg:w-80 lg:border-l lg:border-t-0">
      <div className="shrink-0 space-y-2 border-b border-line px-3 py-2.5 lg:space-y-3 lg:px-4 lg:py-3">
        <div>
          <div className="text-sm font-semibold text-ink">当前对象类别</div>
          <div className="mt-1 hidden text-xs text-gray-500 sm:block">绘制新对象时使用；已有对象可在下方单独修改。</div>
        </div>
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="h-3 w-3 shrink-0 rounded-full border border-line bg-gray-200"
            style={activeClass?.color ? { backgroundColor: activeClass.color, borderColor: activeClass.color } : undefined}
          />
          <input
            aria-label="当前对象类别"
            list="annotation-class-options"
            value={activeLabel}
            title={activeLabel}
            onChange={(event) => onActiveLabelChange(event.target.value)}
            placeholder="搜索或输入新类别"
            className="h-10 min-w-0 flex-1 rounded-lg border border-line bg-white px-3 text-sm outline-none transition focus:border-gray-900 focus-visible:ring-2 focus-visible:ring-gray-300"
          />
          <datalist id="annotation-class-options">
            {annotationClasses.map((annotationClass) => (
              <option key={annotationClass.id} value={annotationClass.name} />
            ))}
          </datalist>
          {canCreateClass && (
            <button
              type="button"
              onClick={onCreateClass}
              disabled={creatingClass}
              className="inline-flex h-10 shrink-0 items-center justify-center gap-1 rounded-lg border border-line px-2.5 text-xs font-medium text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              <Plus size={15} />
              新建
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onSyncClassesToTags}
          disabled={!sampleAvailable || saving || objects.length === 0 || dirty || draftActive}
          title="将当前对象类别追加为样本标签；不会删除或替换已有标签"
          className="inline-flex min-h-9 items-center gap-2 text-xs font-medium text-gray-500 hover:text-gray-900 disabled:cursor-not-allowed disabled:text-gray-300"
        >
          <Tags size={15} />
          将对象类别追加到样本标签
        </button>
      </div>
      <div className="flex shrink-0 items-center justify-between border-b border-line px-3 py-2 lg:block lg:px-4 lg:py-3">
        <div className="text-sm font-semibold text-ink">标注对象</div>
        <div className="text-xs text-gray-500 lg:mt-1">{objects.length} 个对象</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {!sampleAvailable ? (
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-line px-4 text-center text-sm text-gray-500">
            当前队列没有可处理的图片
          </div>
        ) : objects.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-line text-sm text-gray-500">
            暂无标注对象
          </div>
        ) : (
          <div className="space-y-2">
            {objects.map((object, index) => {
              const active = object.client_id === activeObjectId;
              const annotationClass = classByName.get(object.label.toLowerCase());
              return (
                <div
                  key={object.client_id}
                  className={`rounded-lg border bg-white p-3 shadow-sm ${
                    active ? "border-gray-900" : "border-line"
                  }`}
                >
                  <button
                    type="button"
                    title="选择并聚焦对象"
                    onClick={() => onSelect(object.client_id)}
                    className="flex w-full items-start justify-between gap-3 text-left"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-ink">{objectTitle(object, index)}</div>
                      <div className="mt-1 text-xs text-gray-500">{object.shape_type}</div>
                    </div>
                    <span
                      className="rounded-md border border-line bg-gray-50 px-2 py-0.5 text-xs text-gray-600"
                      style={tagChipStyle(annotationClass?.color)}
                    >
                      {index + 1}
                    </span>
                  </button>
                  {active && (
                    <div className="mt-3 space-y-3 border-t border-line pt-3">
                      <label className="block">
                        <span className="text-xs font-medium text-gray-500">类别</span>
                        <select
                          value={object.label}
                          onChange={(event) =>
                            onUpdate(object.client_id, {
                              label: event.target.value,
                              class_id:
                                annotationClasses.find((item) => item.name.toLowerCase() === event.target.value.toLowerCase())?.id ??
                                null
                            })
                          }
                          className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900"
                        >
                          {object.label && !annotationClasses.some((item) => item.name === object.label) && (
                            <option value={object.label}>{object.label}</option>
                          )}
                          {annotationClasses.map((item) => (
                            <option key={item.id} value={item.name}>
                              {item.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        <span className="text-xs font-medium text-gray-500">备注</span>
                        <textarea
                          value={object.notes ?? ""}
                          onChange={(event) => onUpdate(object.client_id, { notes: event.target.value || null })}
                          className="mt-1 min-h-20 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none transition focus:border-gray-900"
                        />
                      </label>
                      <fieldset>
                        <legend className="text-xs font-medium text-gray-500">训练属性</legend>
                        <div className="mt-2 grid grid-cols-3 gap-2">
                          {[
                            ["occluded", "遮挡"],
                            ["truncated", "截断"],
                            ["difficult", "困难"]
                          ].map(([key, label]) => (
                            <label key={key} className="flex items-center gap-1.5 rounded-md border border-line px-2 py-2 text-xs text-gray-700">
                              <input
                                type="checkbox"
                                checked={Boolean(object.attributes[key])}
                                onChange={(event) =>
                                  onUpdate(object.client_id, {
                                    attributes: { ...object.attributes, [key]: event.target.checked }
                                  })
                                }
                                className="h-4 w-4 rounded border-gray-300"
                              />
                              {label}
                            </label>
                          ))}
                        </div>
                      </fieldset>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => onUpdate(object.client_id, { hidden: !object.hidden })}
                          className="inline-flex h-9 flex-1 items-center justify-center gap-2 rounded-lg border border-line text-sm text-gray-700 hover:bg-gray-50"
                        >
                          {object.hidden ? <EyeOff size={16} /> : <Eye size={16} />}
                          {object.hidden ? "隐藏" : "显示"}
                        </button>
                        <button
                          type="button"
                          onClick={() => onUpdate(object.client_id, { locked: !object.locked })}
                          className="inline-flex h-9 flex-1 items-center justify-center gap-2 rounded-lg border border-line text-sm text-gray-700 hover:bg-gray-50"
                        >
                          {object.locked ? <Lock size={16} /> : <Unlock size={16} />}
                          {object.locked ? "锁定" : "可编辑"}
                        </button>
                        <button
                          type="button"
                          title="删除对象"
                          onClick={() => onDelete(object.client_id)}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-red-200 text-red-700 hover:bg-red-50"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="shrink-0 space-y-2 border-t border-line bg-gray-50/80 p-3">
        <button
          type="button"
          onClick={onSaveAndNext}
          disabled={!sampleAvailable || saving || draftActive || (completedWithoutChanges && !hasQueueContinuation)}
          aria-busy={saving}
          className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 text-sm font-semibold text-white transition hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {objects.length > 0 ? <CheckCircle2 size={18} /> : <CircleSlash2 size={18} />}
          {saving ? "保存中" : completionLabel}
        </button>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={onSaveDraft}
            disabled={!sampleAvailable || saving || draftActive || !dirty}
            className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
          >
            <Save size={15} />
            保存草稿
          </button>
          <button
            type="button"
            onClick={onCompleteCurrent}
            disabled={!sampleAvailable || saving || draftActive || completedWithoutChanges}
            className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
          >
            {objects.length > 0 ? <CheckCircle2 size={15} /> : <CircleSlash2 size={15} />}
            {completedWithoutChanges ? "当前已完成" : objects.length > 0 ? "仅完成当前" : "仅确认无目标"}
          </button>
        </div>
        <p className={`${queueCompleted ? "" : "hidden sm:block"} text-center text-[11px] leading-4 text-gray-500`}>
          {queueCompleted
            ? "本队列已处理完成，可返回数据集或切换队列。"
            : "完成会进入待审核；保存草稿仍保留在待处理队列。"}
        </p>
      </div>
    </aside>
  );
}
