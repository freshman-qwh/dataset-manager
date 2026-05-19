import { Eye, EyeOff, Lock, Trash2, Unlock } from "lucide-react";

import type { AnnotationObject, Tag } from "../../types/dataset";
import { tagChipStyle } from "../../utils/colors";

interface AnnotationObjectListProps {
  objects: AnnotationObject[];
  activeObjectId: string | null;
  tags: Tag[];
  onSelect: (clientId: string) => void;
  onUpdate: (clientId: string, updates: Partial<AnnotationObject>) => void;
  onDelete: (clientId: string) => void;
}

function objectTitle(object: AnnotationObject, index: number): string {
  return object.label || `对象 ${index + 1}`;
}

export default function AnnotationObjectList({
  objects,
  activeObjectId,
  tags,
  onSelect,
  onUpdate,
  onDelete
}: AnnotationObjectListProps) {
  const tagByName = new Map(tags.map((tag) => [tag.name.toLowerCase(), tag]));

  return (
    <aside className="flex h-72 min-h-0 w-full shrink-0 flex-col overflow-hidden border-t border-line bg-white lg:h-auto lg:w-80 lg:border-l lg:border-t-0">
      <div className="shrink-0 border-b border-line px-4 py-3">
        <div className="text-sm font-semibold text-ink">标注对象</div>
        <div className="mt-1 text-xs text-gray-500">{objects.length} 个对象</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {objects.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-line text-sm text-gray-500">
            暂无标注对象
          </div>
        ) : (
          <div className="space-y-2">
            {objects.map((object, index) => {
              const active = object.client_id === activeObjectId;
              const tag = tagByName.get(object.label.toLowerCase());
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
                      style={tagChipStyle(tag?.color)}
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
                              tag_id:
                                tags.find((item) => item.name.toLowerCase() === event.target.value.toLowerCase())?.id ??
                                null
                            })
                          }
                          className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition focus:border-gray-900"
                        >
                          {object.label && !tags.some((tagItem) => tagItem.name === object.label) && (
                            <option value={object.label}>{object.label}</option>
                          )}
                          {tags.map((tagItem) => (
                            <option key={tagItem.id} value={tagItem.name}>
                              {tagItem.name}
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
    </aside>
  );
}
