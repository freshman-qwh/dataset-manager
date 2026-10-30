import axios from "axios";
import { useState } from "react";
import { restoreWorkspace } from "../api/client";
import DirectoryPickerModal from "./DirectoryPickerModal";

export default function WorkspaceRestore() {
  const [path, setPath] = useState("");
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState("");
  return <details className="mt-4 rounded-lg border border-line p-3"><summary className="cursor-pointer text-sm font-medium">校验并恢复元数据 ZIP</summary>
    <div className="mt-3 space-y-3 text-sm"><p className="text-gray-500">恢复到新工作区，不替换当前数据。包含数据库及必要快照、计划、任务恢复元数据；原始图片需另行保留或重新挂载。</p>
      <label className="block">元数据 ZIP 路径<div className="mt-1 flex gap-2"><input aria-label="恢复包路径" className="min-w-0 flex-1 rounded-lg border p-2" value={path} disabled={busy} onChange={e => { setPath(e.target.value); setResult(null); }} /><button disabled={busy} onClick={() => setPicker(true)}>浏览</button></div></label>
      <button disabled={busy || !path} className="rounded-lg border px-4 py-2 disabled:opacity-40" onClick={() => { setBusy(true); setError(""); setResult(null); void restoreWorkspace(path).then(r => setResult(r.target_directory)).catch(e => setError(axios.isAxiosError(e) ? String(e.response?.data?.detail ?? "恢复未完成，请检查备份后重试。") : "恢复失败。")).finally(() => setBusy(false)); }}>{busy ? "正在校验并恢复…" : "恢复到新工作区"}</button>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {result && <div role="status" className="space-y-2 rounded-lg bg-emerald-50 p-3 text-emerald-900"><p>恢复校验通过，当前工作区保持原样。</p><p className="break-all">新位置：{result}</p><p>请先安全退出程序。便携版可用 DatasetManager.exe --workspace 加上此新位置启动；源码版按恢复说明设置数据库和存储目录。原图移动后使用目录修复预览重新挂载。</p></div>}
    </div>
    <DirectoryPickerModal open={picker} mode="file" extensions=".zip" onClose={() => setPicker(false)} onSelect={setPath} />
  </details>;
}
