import axios from "axios";
import { Loader2, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { confirmBatchReception, getReceptionPlan, getReceptionProfile, previewBatchReception, saveReceptionProfile } from "../api/batchReception";
import { getOrganization, organizationError } from "../api/organization";
import type { ReceptionPlan, ReceptionProfile, ReceptionProfileRead } from "../types/batchReception";
import type { DatasetOrganization } from "../types/organization";
import Modal from "./Modal";

interface Props {
  datasetId: number;
  initialBatchId?: number;
  onClose: () => void;
  onApplied: () => void | Promise<void>;
  onScan?: () => void;
}

const formats: Record<ReceptionProfile["import_format"], string> = { auto: "自动识别", folder: "普通本地目录", mvtec_ad: "MVTec AD", visa: "VisA" };
const buttonClass = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40";
const primaryClass = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40";
const inputClass = "mt-1 min-h-10 w-full min-w-0 rounded-lg border border-line bg-white px-3 py-2 text-sm disabled:opacity-50";

function receptionError(cause: unknown, fallback: string): string {
  const detail: unknown = axios.isAxiosError(cause) ? cause.response?.data?.detail : undefined;
  if (Array.isArray(detail)) {
    const first: unknown = detail[0];
    if (first && typeof first === "object" && "msg" in first && typeof first.msg === "string") return first.msg.replace(/^Value error, /, "");
  }
  return organizationError(cause, fallback);
}

export default function BatchReceptionModal(props: Props) {
  return <ReceptionContent key={props.datasetId} {...props} />;
}

function ReceptionContent({ datasetId, initialBatchId, onClose, onApplied, onScan }: Props) {
  const [loaded, setLoaded] = useState<ReceptionProfileRead | null>(null);
  const [organization, setOrganization] = useState<DatasetOrganization | null>(null);
  const [draft, setDraft] = useState<ReceptionProfile | null>(null);
  const [batch, setBatch] = useState(initialBatchId ? String(initialBatchId) : "");
  const [plan, setPlan] = useState<ReceptionPlan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [operation, setOperation] = useState<"load" | "save" | "preview" | "page" | "apply" | null>("load");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const operationRef = useRef(operation);
  operationRef.current = operation;
  const dirty = Boolean(draft && loaded && (!loaded.saved || JSON.stringify(draft) !== JSON.stringify(loaded.profile)));
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const pendingActionRef = useRef(pendingAction);
  pendingActionRef.current = pendingAction;
  const closeRef = useRef<() => void>(() => undefined);
  const busy = operation !== null;

  function clearPlan() { setPlan(null); setConfirmation(""); }
  function edit(value: ReceptionProfile) { setDraft(value); clearPlan(); setNotice(""); }
  function requestAction(action: () => void) {
    if (operationRef.current === "save" || operationRef.current === "apply") return;
    if (dirtyRef.current) setPendingAction(() => action);
    else { request.current?.abort(); action(); }
  }
  closeRef.current = () => {
    if (pendingActionRef.current && !operationRef.current) { setPendingAction(null); return; }
    requestAction(onClose);
  };

  useEffect(() => {
    const controller = new AbortController();
    request.current?.abort(); request.current = controller;
    setOperation("load"); setError("");
    void Promise.all([getReceptionProfile(datasetId, controller.signal), getOrganization(datasetId, controller.signal)])
      .then(([value, organizationValue]) => {
        if (controller.signal.aborted) return;
        setLoaded(value); setDraft(value.profile); setOrganization(organizationValue); clearPlan();
        if (initialBatchId && organizationValue.batches.some(item => item.id === initialBatchId)) setBatch(String(initialBatchId));
      }).catch(cause => { if (!controller.signal.aborted) setError(receptionError(cause, "接收方案读取失败，请重试。")); })
      .finally(() => { if (!controller.signal.aborted) setOperation(null); });
    return () => controller.abort();
  }, [datasetId, refresh]);

  useEffect(() => {
    mounted.current = true;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    root.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!dirtyRef.current && operationRef.current !== "save" && operationRef.current !== "apply") return;
      event.preventDefault(); event.returnValue = "";
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const controls = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') ?? [])
        .filter(element => element.getClientRects().length > 0);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    window.addEventListener("beforeunload", beforeUnload); window.addEventListener("keydown", onKey);
    return () => { mounted.current = false; request.current?.abort(); document.body.style.overflow = previousOverflow; previousFocus?.focus(); window.removeEventListener("beforeunload", beforeUnload); window.removeEventListener("keydown", onKey); };
  }, []);

  useEffect(() => {
    if (pendingAction) root.current?.querySelector<HTMLButtonElement>('[data-reception-leave] button')?.focus();
  }, [pendingAction]);

  async function save(): Promise<boolean> {
    if (!draft || !loaded || operationRef.current) return false;
    const controller = new AbortController(); request.current = controller;
    setOperation("save"); setError(""); clearPlan();
    try {
      const next = await saveReceptionProfile(datasetId, loaded.dataset_revision, draft, controller.signal);
      if (!mounted.current || controller.signal.aborted) return false;
      setLoaded(next); setDraft(next.profile); setNotice("接收方案已保存；后续扫描可沿用导入格式，本批元数据仍需预览后确认。");
      return true;
    } catch (cause) {
      if (!controller.signal.aborted && mounted.current) setError(receptionError(cause, "方案保存失败，输入已保留。请核对后重试；若数据版本已变，需重新读取。"));
      return false;
    } finally { if (mounted.current && !controller.signal.aborted) setOperation(null); }
  }

  async function preview() {
    if (!loaded || !batch || dirty || operationRef.current) return;
    const controller = new AbortController(); request.current = controller;
    setOperation("preview"); setError(""); setNotice(""); clearPlan();
    try { const next = await previewBatchReception(datasetId, Number(batch), loaded.dataset_revision, controller.signal); if (mounted.current && !controller.signal.aborted) setPlan(next); }
    catch (cause) { if (mounted.current && !controller.signal.aborted) setError(receptionError(cause, "本批预览失败，请检查图片和数据版本后重试。")); }
    finally { if (mounted.current && !controller.signal.aborted) setOperation(null); }
  }

  async function changePage(page: number) {
    if (!plan || operationRef.current) return;
    const controller = new AbortController(); request.current = controller;
    setOperation("page"); setError("");
    try { const next = await getReceptionPlan(datasetId, plan.plan_id, page, controller.signal); if (mounted.current && !controller.signal.aborted) setPlan(next); }
    catch (cause) { if (mounted.current && !controller.signal.aborted) setError(receptionError(cause, "预览页读取失败，请重试。")); }
    finally { if (mounted.current && !controller.signal.aborted) setOperation(null); }
  }

  async function apply() {
    if (!plan || operationRef.current || confirmation !== plan.confirmation || plan.summary.blocked || dirty) return;
    const controller = new AbortController(); request.current = controller;
    setOperation("apply"); setError(""); setNotice("");
    try {
      const result = await confirmBatchReception(datasetId, plan, confirmation, controller.signal);
      if (!mounted.current || controller.signal.aborted) return;
      setLoaded(value => value ? { ...value, dataset_revision: result.dataset_revision } : value);
      clearPlan();
      setNotice(`已确认接收并补充 ${result.updated_count} 张图片的类别或工件信息；人工判定、划分和原图保持原值。`);
      try { await onApplied(); }
      catch { if (mounted.current) setError("接收已成功，但页面刷新失败，请关闭后重新打开数据集。请勿把刷新失败当作接收未完成。"); }
    } catch (cause) { if (mounted.current && !controller.signal.aborted) setError(receptionError(cause, "接收未确认成功，请核对服务器状态或重新预览后再试。")); }
    finally { if (mounted.current && !controller.signal.aborted) setOperation(null); }
  }

  const categoryName = (id: number | null) => id === null ? "未分配类别" : organization?.categories.find(item => item.id === id)?.name ?? `类别 ${id}`;
  return <div ref={root}><Modal open title="新批次接收方案" onClose={() => closeRef.current()} size="xl" dismissible={operation !== "save" && operation !== "apply"}>
    <div className="min-w-0 space-y-4 p-4 sm:p-5">
      <p className="text-sm leading-6 text-gray-600">1 保存复用规则 → 2 添加本批图片并完成扫描 → 3 预览本批类别与工件变更后确认。只填补空值，不自动改变人工判定或划分。</p>
      {error && <div role="alert" className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><p>{error}</p><button type="button" className={buttonClass} disabled={busy} onClick={() => requestAction(() => setRefresh(value => value + 1))}><RefreshCw size={15} />重新读取</button></div>}
      {notice && <p role="status" className="rounded-lg bg-gray-50 p-3 text-sm text-gray-700">{notice}</p>}
      {operation === "load" && <p role="status" className="flex items-center gap-2 text-sm text-gray-500"><Loader2 size={18} className="animate-spin" />正在读取接收方案与批次…</p>}
      {pendingAction && <div data-reception-leave className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3"><p className="text-sm text-amber-900">接收方案有未保存修改。请保存后继续，或明确放弃本次编辑。</p><div className="flex flex-wrap gap-2"><button type="button" disabled={busy} className={primaryClass} onClick={() => void save().then(ok => { if (ok && pendingAction) { const action = pendingAction; setPendingAction(null); action(); } })}>保存并继续</button><button type="button" disabled={busy} className={buttonClass} onClick={() => { const action = pendingAction; if (loaded) setDraft(loaded.profile); setPendingAction(null); request.current?.abort(); action?.(); }}>放弃修改</button><button type="button" disabled={busy} className={buttonClass} onClick={() => setPendingAction(null)}>取消</button></div></div>}
      {loaded && draft && organization && <>
        <div className="rounded-lg border border-line bg-gray-50 p-3 text-xs leading-6 text-gray-600">当前数据集沿用分拣标准（版本 {loaded.context.policy_version}）、已有参考卡和{loaded.context.roi ? "固定检测区域" : "整张图检测范围"}。保存本方案不复制或改写这些设置，也不影响历史实验。</div>
        <fieldset disabled={busy || Boolean(pendingAction)} className="min-w-0 space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold">本数据集接收方案</legend>
          <div className="grid gap-3 sm:grid-cols-2"><label className="min-w-0 text-sm">方案名称<input aria-label="接收方案名称" className={inputClass} maxLength={160} value={draft.name} onChange={event => edit({ ...draft, name: event.target.value })} /></label><label className="min-w-0 text-sm">下次扫描导入格式<select aria-label="接收方案导入格式" className={inputClass} value={draft.import_format} onChange={event => edit({ ...draft, import_format: event.target.value as ReceptionProfile["import_format"] })}>{Object.entries(formats).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" aria-label="按文件名提取工件组" checked={Boolean(draft.filename_rule)} onChange={event => edit({ ...draft, filename_rule: event.target.checked ? { delimiter: "_", keep_segments: 2, include_parent: false } : null })} />按文件名提取工件组</label>
          {draft.filename_rule && <div className="space-y-2 rounded-lg bg-gray-50 p-3"><p className="text-xs leading-5 text-gray-600">例如 part_001_camA 按下划线保留前 2 段，得到 part_001；同一工件的不同视角应得到相同编号。</p><div className="flex flex-wrap gap-3"><label className="text-sm">分隔符<select aria-label="接收工件分隔符" className={inputClass} value={draft.filename_rule.delimiter} onChange={event => edit({ ...draft, filename_rule: { ...draft.filename_rule!, delimiter: event.target.value as "_" | "-" | " " } })}><option value="_">下划线 _</option><option value="-">短横线 -</option><option value=" ">空格</option></select></label><label className="text-sm">保留前几段<input aria-label="接收工件保留段数" type="number" min={1} max={8} className={`${inputClass} !w-24`} value={draft.filename_rule.keep_segments} onChange={event => edit({ ...draft, filename_rule: { ...draft.filename_rule!, keep_segments: Number(event.target.value) } })} /></label></div><label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={draft.filename_rule.include_parent} onChange={event => edit({ ...draft, filename_rule: { ...draft.filename_rule!, include_parent: event.target.checked } })} />工件编号包含父目录，区分不同目录中的同名工件</label></div>}
          <div className="space-y-2"><p className="text-sm font-medium">目录前缀 → 对象类别</p><p className="text-xs leading-5 text-gray-500">按图片相对目录匹配；“.”表示扫描根目录与兜底，较长的目录规则优先。已有不同类别或工件编号时阻断本批确认，不覆盖原值。</p>
            {draft.category_rules.map((rule, index) => <div key={index} className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-end gap-2"><label className="min-w-0 text-xs text-gray-600">相对目录<input aria-label={`目录规则 ${index + 1}`} className={inputClass} maxLength={2000} placeholder="例如 product-a/camera-1" value={rule.directory} onChange={event => edit({ ...draft, category_rules: draft.category_rules.map((item, position) => position === index ? { ...item, directory: event.target.value } : item) })} /></label><label className="min-w-0 text-xs text-gray-600">对象类别<select aria-label={`规则类别 ${index + 1}`} className={inputClass} value={rule.category_id} onChange={event => edit({ ...draft, category_rules: draft.category_rules.map((item, position) => position === index ? { ...item, category_id: Number(event.target.value) } : item) })}>{organization.categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label><button type="button" aria-label={`删除目录规则 ${index + 1}`} className={buttonClass} onClick={() => edit({ ...draft, category_rules: draft.category_rules.filter((_, position) => position !== index) })}><Trash2 size={15} /></button></div>)}
            <button type="button" disabled={organization.categories.length === 0 || draft.category_rules.length >= 200} className={buttonClass} onClick={() => edit({ ...draft, category_rules: [...draft.category_rules, { directory: "", category_id: organization.categories[0].id }] })}><Plus size={15} />添加类别映射</button>
            {organization.categories.length === 0 && <p className="text-xs text-gray-500">当前没有对象类别；可先在数据集的类别与批次管理中添加，或暂不使用类别映射。</p>}
          </div>
          <div className="flex flex-wrap items-center gap-3"><button type="button" className={primaryClass} disabled={!dirty || !draft.name.trim()} onClick={() => void save()}><Save size={15} />保存接收方案</button>{dirty && <span className="text-xs text-amber-800">方案修改尚未保存；保存后再预览本批。</span>}</div>
        </fieldset>
        <fieldset disabled={busy || Boolean(pendingAction)} className="space-y-3 rounded-lg border border-line p-3"><legend className="px-1 text-sm font-semibold">本批接收预览</legend>
          <label className="block text-sm">已完成扫描的采集批次<select aria-label="接收采集批次" className={inputClass} value={batch} onChange={event => { setBatch(event.target.value); clearPlan(); setNotice(""); }}><option value="">请选择本批</option>{organization.batches.map(item => <option key={item.id} value={item.id}>{item.name} · {item.sample_count} 张</option>)}</select></label>
          <p className="text-xs leading-5 text-gray-500">先在“添加图片”中指定或新建批次并完成扫描。扫描结果说明新增、更新、未变和缺失；下面只整理所选已登记批次，不重新分配历史图片的批次。</p>
          <div className="flex flex-wrap gap-2">{onScan && <button type="button" className={buttonClass} onClick={() => requestAction(onScan)}>添加本批图片</button>}<button type="button" className={primaryClass} disabled={!batch || dirty} onClick={() => void preview()}>预览本批接收</button></div>
        </fieldset>
        {plan && <section aria-label="本批接收预览结果" className="min-w-0 space-y-3 rounded-lg border border-line p-3">
          <h3 className="break-all text-sm font-semibold">{plan.summary.batch_name} · 接收前核对</h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{[["本批图片", plan.summary.image_count], ["尚未分拣", plan.summary.untriaged_count], ["重复内容", plan.summary.duplicate_count], ["未匹配规则", plan.summary.unmatched_count], ["已有值冲突", plan.summary.conflict_count], ["拟补充信息", plan.summary.updated_count]].map(([label, count]) => <div key={label} className="rounded-lg bg-gray-50 p-2 text-xs text-gray-600"><p>{label}</p><strong className="mt-1 block text-lg text-gray-900">{count}</strong></div>)}</div>
          {plan.summary.blockers.map((message, index) => <p key={index} role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{message}</p>)}
          {plan.summary.unmatched_count > 0 && <p className="text-xs leading-5 text-amber-800">未匹配图片可保持空值。请检查示例，按需补充规则后重新预览。</p>}
          <div className="max-h-64 overflow-auto"><table className="w-full min-w-[600px] text-left text-xs"><thead><tr>{["图片", "类别：原值 → 本次", "工件：原值 → 本次", "说明"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{plan.rows.map(row => <tr key={row.sample_id} className="border-t border-line"><td className="max-w-56 break-all p-2">{row.relative_path}</td><td className="max-w-44 break-words p-2">{categoryName(row.before_category_id)} → {categoryName(row.category_id)}</td><td className="max-w-48 break-all p-2">{row.before_group || "未填写"} → {row.capture_group_id || "保持未填写"}</td><td className="max-w-52 break-words p-2">{row.reason || (row.changed ? "仅填补空值" : "保持原值")}</td></tr>)}</tbody></table></div>
          <div className="flex flex-wrap items-center gap-3 text-sm"><button type="button" className={buttonClass} disabled={busy || plan.page <= 1} onClick={() => void changePage(plan.page - 1)}>上一页</button><span>第 {plan.page} / {Math.max(1, Math.ceil(plan.total / plan.page_size))} 页 · 共 {plan.total} 张</span><button type="button" className={buttonClass} disabled={busy || plan.page * plan.page_size >= plan.total} onClick={() => void changePage(plan.page + 1)}>下一页</button></div>
          <p className="text-xs leading-5 text-gray-500">只补充本批图片中为空的类别与工件字段；不改批次、人工判定、训练划分和原图。数据、方案或原图变化后需重新预览。</p>
          <label className="block break-words text-sm">输入“{plan.confirmation}”<input aria-label="接收确认文字" className={inputClass} value={confirmation} disabled={busy || plan.summary.blocked || Boolean(pendingAction)} onChange={event => setConfirmation(event.target.value)} /></label>
          <button type="button" className={primaryClass} disabled={busy || dirty || Boolean(pendingAction) || plan.summary.blocked || plan.summary.updated_count === 0 || confirmation !== plan.confirmation} onClick={() => void apply()}>确认接收并补充信息</button>
          {plan.summary.updated_count === 0 && !plan.summary.blocked && <p className="text-xs text-gray-500">本批没有需要补充的空字段，可继续分拣或交付检查。</p>}
        </section>}
      </>}
      {busy && operation !== "load" && <p role="status" className="flex items-center gap-2 text-sm text-gray-600"><Loader2 size={16} className="animate-spin" />{operation === "save" ? "正在保存方案…" : operation === "apply" ? "正在核对并确认接收…" : "正在读取预览…"}</p>}
    </div>
  </Modal></div>;
}
