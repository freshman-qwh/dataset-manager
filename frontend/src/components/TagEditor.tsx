import { KeyboardEvent, useState } from "react";
import { Plus, X } from "lucide-react";

interface TagEditorProps {
  tags: string[];
  onChange: (tags: string[]) => void;
}

export default function TagEditor({ tags, onChange }: TagEditorProps) {
  const [value, setValue] = useState("");

  function addTag() {
    const name = value.trim();
    if (!name) {
      return;
    }
    const exists = tags.some((item) => item.toLowerCase() === name.toLowerCase());
    if (!exists) {
      onChange([...tags, name]);
    }
    setValue("");
  }

  function removeTag(name: string) {
    onChange(tags.filter((item) => item !== name));
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      addTag();
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm outline-none transition focus:border-gray-900"
          placeholder="新增标签"
        />
        <button
          type="button"
          title="添加标签"
          onClick={addTag}
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
          >
            {tag}
            <button type="button" title="移除标签" onClick={() => removeTag(tag)} className="text-gray-400 hover:text-gray-900">
              <X size={13} />
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}
