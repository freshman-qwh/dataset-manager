import { ChevronLeft, FileJson, Folder, HardDrive } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { listDirectories, listLocalFiles } from "../api/client";
import type { DirectoryEntry } from "../types/dataset";
import Modal from "./Modal";

interface DirectoryPickerModalProps {
  open: boolean;
  initialPath?: string;
  mode?: "directory" | "file";
  extensions?: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}

function isUnsafeRoot(path: string | null): boolean {
  if (!path) {
    return true;
  }
  return path === "/" || /^[A-Za-z]:\\?$/.test(path);
}

export default function DirectoryPickerModal({ open, initialPath, mode = "directory", extensions = ".json", onClose, onSelect }: DirectoryPickerModalProps) {
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<(DirectoryEntry & { kind?: "directory" | "file" })[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  async function load(path?: string) {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError(null);
    try {
      const result = mode === "file" ? await listLocalFiles(path, request.signal, extensions) : await listDirectories(path, request.signal);
      if (request.signal.aborted) return;
      setCurrentPath(result.current_path);
      setParentPath(result.parent_path);
      setEntries(result.entries);
    } catch {
      if (request.signal.aborted) return;
      setEntries([]);
      setCurrentPath(null);
      setParentPath(null);
      setError("目录不可读取");
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    if (open) {
      void load(initialPath || undefined);
    }
    return () => controller.current?.abort();
  }, [open, initialPath, mode, extensions]);

  return (
    <Modal open={open} title={mode === "file" ? `选择 ${extensions.toUpperCase()} 文件` : "选择本地目录"} onClose={onClose}>
      <div className="space-y-3 px-5 py-5">
        <div className="flex items-center justify-between gap-3 rounded-lg border border-line bg-gray-50 px-3 py-2 text-sm text-gray-600">
          <span className="min-w-0 break-all" title={currentPath ?? undefined}>{currentPath || "本机"}</span>
          {mode === "directory" && currentPath && (
            <button
              type="button"
              disabled={loading || isUnsafeRoot(currentPath)}
              onClick={() => {
                onSelect(currentPath);
                onClose();
              }}
              className="shrink-0 rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {isUnsafeRoot(currentPath) ? "请选择子目录" : "使用"}
            </button>
          )}
        </div>

        <button type="button" onClick={() => void load()} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2">本机</button>
        {mode === "file" ? <p className="text-xs text-gray-500">仅显示 {extensions.toUpperCase()} 文件；点击文件即可选择。</p> : null}

        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        <div className="max-h-96 overflow-y-auto rounded-lg border border-line">
          {currentPath && (
            <button
              type="button"
              disabled={loading || !parentPath}
              onClick={() => void load(parentPath || undefined)}
              className="flex w-full items-center gap-2 border-b border-line px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              <ChevronLeft size={17} />
              上一级
            </button>
          )}
          {loading ? (
            <div className="px-3 py-8 text-center text-sm text-gray-500">加载中</div>
          ) : entries.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-gray-500">{mode === "file" ? "没有匹配文件或子目录" : "没有可选子目录"}</div>
          ) : (
            entries.map((entry) => (
              <button
                key={entry.path}
                type="button"
                onClick={() => {
                  if (entry.kind === "file") { onSelect(entry.path); onClose(); }
                  else void load(entry.path);
                }}
                className="flex w-full items-center gap-2 border-b border-line px-3 py-2.5 text-left text-sm text-gray-700 last:border-0 hover:bg-gray-50"
              >
                {entry.kind === "file" ? <FileJson size={17} className="shrink-0 text-gray-400" /> : currentPath ? <Folder size={17} className="shrink-0 text-gray-400" /> : <HardDrive size={17} className="shrink-0 text-gray-400" />}
                <span className="min-w-0 truncate">{entry.name}</span>
              </button>
            ))
          )}
        </div>
      </div>
    </Modal>
  );
}
