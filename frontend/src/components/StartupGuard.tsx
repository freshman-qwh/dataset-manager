import { type ReactNode, useEffect, useState } from "react";
import { getStartupStatus } from "../api/client";

export default function StartupGuard({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<{needs_upgrade: boolean; database_path: string} | null>(null);
  const [error, setError] = useState(false);
  const [checking, setChecking] = useState(true);
  async function check() {
    setChecking(true); setError(false);
    try { setStatus(await getStartupStatus()); } catch { setError(true); }
    finally { setChecking(false); }
  }
  useEffect(() => { void check(); }, []);
  if (checking) return <p role="status" className="p-8 text-sm text-gray-500">正在检查本地工作区…</p>;
  if (error || status?.needs_upgrade) return <main className="mx-auto my-16 max-w-xl space-y-4 rounded-xl border bg-white p-6">
    <h1 className="text-xl font-semibold">{error ? "本地服务暂未就绪" : "工作区需要升级后继续"}</h1>
    <p className="text-sm text-gray-600">{error ? "请确认程序已启动，再重新检查。" : "当前数据保留。便携版请安全退出后，用新版本启动器重新打开；启动器会先备份并校验，再完成升级。"}</p>
    {status?.needs_upgrade && <details className="text-sm"><summary className="cursor-pointer">源码运行与维护说明</summary><p className="mt-3">关闭后端，按 README.zh-CN.md 的数据库维护步骤备份升级，再重启服务。请先确认维护对象是下列数据库。</p><p className="mt-2 break-all text-gray-500">{status.database_path}</p></details>}
    <button className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white" onClick={() => void check()}>重新检查</button>
  </main>;
  return <>{children}</>;
}
