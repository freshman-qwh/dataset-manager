import { KeyboardEvent, useState } from "react";
import { Plus, X } from "lucide-react";

import type { Tag } from "../types/dataset";
import { tagChipStyle } from "../utils/colors";

interface TagEditorProps {
  tags: string[];
  options?: Tag[];
  onChange: (tags: string[]) => void;
}

export default function TagEditor({ tags, options = [], onChange }: TagEditorProps) {
  const [value, setValue] = useState("");
  const optionByName = new Map(options.map((tag) => [tag.name.toLowerCase(), tag]));

  function addTag(rawName = value) {
    const name = rawName.trim();
    if (!name) {
      return;
    }
    const exists = tags.some((item) => item.toLowerCase() === name.toLowerCase());
    if (!exists) {
      onChange([...tags, name]);
    }
    setValue("");
  }

  function toggleExistingTag(name: string) {
    const exists = tags.some((item) => item.toLowerCase() === name.toLowerCase());
    if (exists) {
      removeTag(name);
    } else {
      addTag(name);
    }
  }

  function removeTag(name: string) {
    onChange(tags.filter((item) => item.toLowerCase() !== name.toLowerCase()));
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      addTag();
    }
  }

  return (
    <div className="space-y-2">
      {options.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-gray-500">已有标签</div>
          <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto rounded-lg border border-line bg-gray-50 p-2">
            {options.map((tag) => {
              const selected = tags.some((item) => item.toLowerCase() === tag.name.toLowerCase());
              return (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => toggleExistingTag(tag.name)}
                  className={`rounded-md border px-2 py-1 text-xs transition ${
                    selected ? "border-transparent font-medium shadow-sm" : "border-line bg-white text-gray-600 hover:bg-gray-100"
                  }`}
                  style={selected ? tagChipStyle(tag.color) : undefined}
                >
                  {tag.name}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <div className="flex gap-2">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm outline-none transition focus:border-gray-900"
          placeholder="输入新标签或别名"
        />
        <button
          type="button"
          title="添加标签"
          onClick={() => addTag()}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-gray-900 text-white hover:bg-gray-800"
        >
          <Plus size={17} />
        </button>
      </div>
      <div className="flex min-h-8 flex-wrap gap-2">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-md border border-line bg-gray-50 px-2 py-1 text-xs text-gray-700"
            style={tagChipStyle(optionByName.get(tag.toLowerCase())?.color)}
          >
            {tag}
            <button type="button" title="移除标签" onClick={() => removeTag(tag)} className="text-current opacity-70 hover:opacity-100">
              <X size={13} />
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}
