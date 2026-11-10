import { useEffect, useRef, useState } from "react";
import { getOrganization, organizationError, previewImport } from "../api/organization";
import { getReceptionProfile } from "../api/batchReception";
import type { DatasetBatch, ImportPreview, ScanOptions } from "../types/organization";

const formats: Record<string, string> = { auto: "自动识别", folder: "普通本地目录", mvtec_ad: "MVTec AD", visa: "VisA" };

export default function ScanImportFields({ datasetId, open, path, disabled, receptionEnabled = false, onChange, onValidityChange }: { datasetId: number; open: boolean; path: string; disabled: boolean; receptionEnabled?: boolean; onChange: (options: ScanOptions) => void; onValidityChange: (valid: boolean) => void }) {
  const [batches, setBatches] = useState<DatasetBatch[]>([]);
  const [batch, setBatch] = useState("");
  const [newName, setNewName] = useState("");
  const [format, setFormat] = useState<NonNullable<ScanOptions["import_format"]>>("auto");
  const [recognizeExisting, setRecognizeExisting] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [batchError, setBatchError] = useState(false);
  const [version, setVersion] = useState(0);
  const [profileName, setProfileName] = useState("");
  const [profileFormat, setProfileFormat] = useState<NonNullable<ScanOptions["import_format"]>>("auto");
  const controllerRef = useRef<AbortController | null>(null);
  const options: ScanOptions = { import_format: format, recognize_existing: recognizeExisting, ...(batch === "new" ? { new_batch_name: newName.trim() } : batch ? { batch_id: Number(batch) } : {}) };
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setBatchError(false);
    void getOrganization(datasetId, controller.signal).then((data) => setBatches(data.batches)).catch(() => { if (!controller.signal.aborted) setBatchError(true); });
    return () => controller.abort();
  }, [datasetId, open, version]);
  useEffect(() => {
    if (!open || !receptionEnabled) return;
    const controller = new AbortController();
    void getReceptionProfile(datasetId, controller.signal).then(data => {
      if (controller.signal.aborted || !data.saved) return;
      setProfileName(data.profile.name);
      setProfileFormat(data.profile.import_format);
    }).catch(() => { /* Reception profiles are optional; ordinary scanning stays available. */ });
    return () => controller.abort();
  }, [datasetId, open, receptionEnabled]);
  useEffect(() => { onChange({ import_format: format, recognize_existing: recognizeExisting, ...(batch === "new" ? {new_batch_name: newName.trim()} : batch ? {batch_id:Number(batch)} : {}) }); }, [batch, format, newName, recognizeExisting, onChange]);
  useEffect(() => { onValidityChange(!checking && (batch !== "new" || Boolean(newName.trim()))); }, [batch, checking, newName, onValidityChange]);
  useEffect(() => { controllerRef.current?.abort(); setPreview(null); setChecking(false); setError(""); return () => controllerRef.current?.abort(); }, [path, batch, format, newName, recognizeExisting, open]);
  async function check() {
    const controller = new AbortController(); controllerRef.current?.abort(); controllerRef.current = controller;
    setChecking(true); setError("");
    try { const data = await previewImport(datasetId, path.trim(), options, controller.signal); if (!controller.signal.aborted) setPreview(data); }
    catch (caught) { if (!controller.signal.aborted) setError(organizationError(caught, "无法识别目录，请检查路径或选择导入格式。")); }
    finally { if (!controller.signal.aborted) setChecking(false); }
  }
  return <fieldset disabled={disabled} className="min-w-0 space-y-3">
    {profileName && <div className="space-y-2 rounded-lg border border-line bg-gray-50 p-3 text-xs text-gray-600"><p>已保存接收方案：{profileName}</p><button type="button" disabled={checking} onClick={() => setFormat(profileFormat)} className="min-h-9 rounded border border-line bg-white px-3 text-sm disabled:opacity-40">使用方案导入格式</button><p>本次选择新批次后扫描；完成后在“整理本次扫描批次”预览类别与工件规则。已有判定、批次和工件不会被扫描覆盖。</p></div>}
    <label className="block text-sm font-medium text-gray-700">采集批次<select aria-label="导入批次" value={batch} onChange={(event) => setBatch(event.target.value)} className="mt-2 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm"><option value="">不指定批次</option>{batches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}<option value="new">＋ 新建批次</option></select></label>
    {batch === "new" && <input aria-label="新批次名称" required maxLength={160} value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="例如 首次采集、补充异常" className="w-full rounded-lg border border-line px-3 py-2.5 text-sm" />}
    <p className="text-xs leading-5 text-gray-500">批次只赋给新增图片，重复扫描保留已有批次、工件组与人工判定。</p>
    {batchError && <p className="text-xs text-red-700">批次列表加载失败。<button type="button" onClick={() => setVersion((value) => value + 1)} className="ml-2 underline">重试</button></p>}
    <details className="rounded-lg border border-line p-3"><summary className="cursor-pointer text-sm text-gray-600">导入格式 · {formats[format]}{recognizeExisting ? " · 补充已有图片" : ""}</summary><select aria-label="导入格式" value={format} onChange={(event) => setFormat(event.target.value as NonNullable<ScanOptions["import_format"]>)} className="mt-3 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm">{Object.entries(formats).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><p className="mt-2 text-xs leading-5 text-gray-500">识别对象类别、官方划分和 mask 关联。原图与 mask 保留原位置。</p><label className="mt-3 flex items-start gap-2 text-sm text-gray-700"><input type="checkbox" aria-label="为已有图片补充识别信息" checked={recognizeExisting} onChange={(event) => setRecognizeExisting(event.target.checked)} className="mt-0.5 h-4 w-4 shrink-0 accent-gray-900" /><span>为已有图片补充识别信息<span className="mt-1 block text-xs leading-5 text-gray-500">仅补充空的类别、官方划分和 mask 关联，保留人工判定、现有划分、批次和工件。</span></span></label></details>
    <button type="button" onClick={() => void check()} disabled={checking || !path.trim() || (batch === "new" && !newName.trim())} className="rounded-lg border border-line px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40">{checking ? "正在检查目录…" : "预览导入内容"}</button>
    {preview && <div role="status" className="space-y-2 rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-600"><p className="font-medium text-gray-800">{formats[preview.detected_format] ?? preview.detected_format} · {preview.image_count} 张图片 · {preview.mask_count} 个 mask</p>{preview.categories.length > 0 && <p className="break-words text-xs leading-5">类别：{preview.categories.join("、")}</p>}{Object.keys(preview.official_split_counts).length > 0 && <p className="text-xs">官方划分：{Object.entries(preview.official_split_counts).map(([key, count]) => `${key} ${count}`).join(" · ")}</p>}{preview.warnings.map((warning, index) => <p key={index} className="text-xs leading-5 text-amber-800">{warning}</p>)}</div>}
    {error && <p role="alert" className="text-sm leading-6 text-red-700">{error}</p>}
  </fieldset>;
}
