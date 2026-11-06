import { useEffect, useState } from "react";
import { listProjects } from "../api/organization";
import type { Project } from "../types/organization";

interface Props { open: boolean; choice: string; newName: string; onChange: (choice: string, newName: string) => void; }
export default function ProjectField({ open, choice, newName, onChange }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setError(false);
    void listProjects(controller.signal).then(setProjects).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [open, version]);
  return <div className="space-y-2"><label className="block text-sm font-medium text-gray-700">所属项目 <span className="font-normal text-gray-400">（可选）</span><select aria-label="所属项目" value={choice} onChange={(event) => onChange(event.target.value, newName)} className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm"><option value="">未归属项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}<option value="new">＋ 新建项目</option></select></label>{choice === "new" && <input aria-label="新项目名称" required maxLength={160} value={newName} onChange={(event) => onChange(choice, event.target.value)} placeholder="例如 探针、绿油锡" className="w-full rounded-lg border border-line px-3 py-2.5 text-sm" />}{error && <p className="text-xs text-red-700">项目列表加载失败。<button type="button" onClick={() => setVersion((value) => value + 1)} className="ml-2 underline">重试</button></p>}</div>;
}
