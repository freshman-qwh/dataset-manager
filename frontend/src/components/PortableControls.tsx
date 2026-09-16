import { FolderOpen, Laptop, Power, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  getPortableRuntime,
  openPortableDataDirectory,
  shutdownPortableRuntime
} from "../api/client";

export default function PortableControls() {
  const [enabled, setEnabled] = useState(false);
  const [controlToken, setControlToken] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    getPortableRuntime()
      .then((runtime) => {
        setEnabled(runtime.enabled);
        setControlToken(runtime.control_token);
      })
      .catch(() => setEnabled(false));
  }, []);

  if (!enabled) return null;

  async function handleOpenDirectory() {
    setBusy(true);
    setMessage(null);
    try {
      if (!controlToken) throw new Error("missing control token");
      await openPortableDataDirectory(controlToken);
    } catch {
      setMessage("无法打开数据目录，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  async function handleShutdown() {
    if (!window.confirm("确定安全退出 Dataset Manager？正在运行的任务将停止。")) return;
    setBusy(true);
    setMessage("正在安全退出，可以关闭此页面");
    try {
      if (!controlToken) throw new Error("missing control token");
      await shutdownPortableRuntime(controlToken);
    } catch {
      setMessage("退出请求失败，请重试");
      setBusy(false);
    }
  }

  return (
    <div className="fixed bottom-4 left-4 z-30">
      {open && (
        <div className="mb-2 w-72 rounded-xl border border-line bg-white p-3 shadow-lg shadow-gray-200/70">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold text-ink">便携版运行中</div>
              <div className="mt-0.5 text-xs text-gray-500">数据独立保存在本机应用目录</div>
            </div>
            <button type="button" aria-label="关闭便携版菜单" onClick={() => setOpen(false)} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100">
              <X size={16} />
            </button>
          </div>
          <div className="mt-3 grid gap-2">
            <button type="button" disabled={busy} onClick={() => void handleOpenDirectory()} className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
              <FolderOpen size={16} />打开数据目录
            </button>
            <button type="button" disabled={busy} onClick={() => void handleShutdown()} className="inline-flex items-center gap-2 rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">
              <Power size={16} />安全退出
            </button>
          </div>
          {message && <div className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{message}</div>}
        </div>
      )}
      <button type="button" onClick={() => setOpen((value) => !value)} className="inline-flex min-h-11 items-center gap-2 rounded-full border border-line bg-white px-4 py-2 text-sm font-medium text-ink shadow-lg shadow-gray-200/70 hover:bg-gray-50">
        <Laptop size={17} />便携版
      </button>
    </div>
  );
}
