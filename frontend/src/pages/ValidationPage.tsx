import ValidationRoiEditor from "../components/ValidationRoiEditor";
import ValidationQualityPanel from "../components/ValidationQualityPanel";
import { getValidationPreparation, saveValidationRoi } from "../api/validation";
import type { ValidationPreparation,NormalizedRoi } from "../types/validation";
import { deleteValidationRun } from "../api/validation";
import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { cancelJob, getDataset, getJob, retryJob } from "../api/client";
import { createValidationRun, getValidationRuntime, installValidationRuntime, listValidationRuns, previewValidation, setValidationRuntime, validationError } from "../api/validation";
import type { Dataset } from "../types/dataset";
import type { FrozenPlan } from "../types/industrial";
import type { ValidationRun, ValidationRuntime } from "../types/validation";
import type { AnnotationExportSampleQuery } from "../types/annotationExport";
import DirectoryPickerModal from "../components/DirectoryPickerModal";

export const validationStages: Record<string, string> = {
  queued:"等待开始", starting:"准备运行", copying_files:"复制并校验输入", loading_algorithm:"载入算法组件（首次可能较慢）", preparing_model:"准备基线模型",
  preparing_weights:"准备预训练权重（首次约 45 MB）", fitting_features:"提取正常特征", fitting_distribution:"建立正常基线",
  predicting:"逐图预测", completed:"完成", creating_runtime:"创建独立环境", installing_runtime:"下载 CPU 组件",
  checking_runtime:"检查环境", cancelled:"已取消", process_stopped:"进程已中断", failed:"运行失败"
};
export const validationStatus: Record<string, string> = {queued:"等待中",running:"运行中",succeeded:"已完成",failed:"失败",cancelled:"已取消",interrupted:"已中断"};

export default function ValidationPage() {
  const {datasetId: datasetParam} = useParams();
  const datasetId = Number(datasetParam);
  const location = useLocation();
  const navigate = useNavigate();
  const context = location.state as {currentQuery?: AnnotationExportSampleQuery; selectedIds?: number[];validationSetup?: {mode:string;model:string;imageSize:number;scope:string;name:string;roi:NormalizedRoi|null}} | null;
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [runtime, setRuntime] = useState<ValidationRuntime | null>(null);
  const [pythonPath, setPythonPath] = useState("");
  const [picker, setPicker] = useState(false);
  const [runs, setRuns] = useState<ValidationRun[]>([]);
  const [mode, setMode] = useState(context?.validationSetup?.mode??"evaluation");
  const [model, setModel] = useState(context?.validationSetup?.model??"padim");
  const [imageSize, setImageSize] = useState(context?.validationSetup?.imageSize??256);
  const [scope, setScope] = useState(context?.validationSetup?.scope??"all");
  const [independent, setIndependent] = useState(false);
  const [name, setName] = useState(context?.validationSetup?.name??"");
  const [preparation,setPreparation]=useState<ValidationPreparation|null>(null);
  const [roi,setRoi]=useState<NormalizedRoi|null>(null);
  const sampleQuery:AnnotationExportSampleQuery=scope==="selected"?{sample_ids:context?.selectedIds}:scope==="current"?context?.currentQuery??{}:{};
  const [plan, setPlan] = useState<FrozenPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preparationNotice,setPreparationNotice]=useState("");
  const refreshRuns = useCallback(async () => { setRuns(await listValidationRuns(datasetId)); }, [datasetId]);
  useEffect(() => {
    let alive = true;
    setPreparation(null);
    void getValidationRuntime().then(r=>{if(alive){setRuntime(r);setPythonPath(r.python_path??"");}}).catch(e=>{if(alive)setError(validationError(e));});
    void Promise.all([getDataset(datasetId), listValidationRuns(datasetId),getValidationPreparation(datasetId)])
      .then(([d, list,prep]) => { if (alive) {setPreparation(prep);setRoi(context?.validationSetup?context.validationSetup.roi:prep.roi); setDataset(d);setRuns(list); } })
      .catch(e => { if (alive) setError(validationError(e)); });
    return () => {alive = false;};
  }, [datasetId]);
  const active = runs.some(r => r.job && ["running","queued"].includes(r.job.status));
  useEffect(() => {
    if (!active) return;
    let alive=true;
    const timer=window.setInterval(() => { void listValidationRuns(datasetId).then(value => {if(alive)setRuns(value);}).catch(() => undefined); }, 1500);
    return () => {alive=false;window.clearInterval(timer);};
  }, [active,datasetId]);
  useEffect(() => {
    const job = runtime?.install_job;
    if (!job || !["queued","running"].includes(job.status)) return;
    let alive=true;
    const timer=window.setInterval(() => { void getJob(job.id).then(async next => {
      if(!alive)return;
      if (["queued","running"].includes(next.status)) setRuntime(r => r ? {...r,install_job:next} : r);
      else {const value=await getValidationRuntime();if(alive){setRuntime(value);setPythonPath(value.python_path ?? "");}}
    }).catch(() => undefined); }, 1500);
    return () => {alive=false;window.clearInterval(timer);};
  }, [runtime?.install_job?.id,runtime?.install_job?.status]);
  async function run(action: () => Promise<void>) {setBusy(true);setError("");try{await action();}catch(e){setError(validationError(e));}finally{setBusy(false);}}
  function invalidate() {setPlan(null);setPreparationNotice("");}
  const counts=plan?.summary.counts as Record<string,{normal:number;abnormal:number}> | undefined;
  return <main className="mx-auto max-w-6xl space-y-5 px-5 py-6">
    <header className="space-y-3"><Link to={`/datasets/${datasetId}`} className="text-sm text-gray-500 hover:text-gray-900">← 返回数据准备</Link><h1 className="text-2xl font-semibold">{dataset?.name ?? "工业数据"} · 快速验证</h1><p className="max-w-3xl text-sm leading-6 text-gray-500">用可信正常图片建立基线，再查看独立验证结果。实验会保留本次分组、人工判定和模型配方，原图保持原样。</p></header>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <details open={!runtime?.ready} className="rounded-xl border border-line bg-white p-5"><summary className="cursor-pointer text-sm font-medium">{runtime?.ready ? `验证组件已就绪 · Anomalib ${runtime.versions.anomalib}` : "准备可选的 CPU 验证组件"}</summary><div className="mt-4 space-y-3 text-sm"><p className="text-gray-500">{runtime?.message ?? "正在检查环境…"}</p><div className="flex flex-wrap gap-2"><label className="min-w-0 flex-1">独立环境的 Python<input aria-label="算法 Python 路径" className="mt-1 w-full rounded-lg border p-2" placeholder="选择已安装 Anomalib 2.7.0 的 Python" value={pythonPath} onChange={e=>setPythonPath(e.target.value)} /></label><button disabled={busy} className="self-end rounded-lg border px-3 py-2" onClick={()=>setPicker(true)}>浏览解释器</button><button disabled={busy || !pythonPath} className="self-end rounded-lg border px-3 py-2 disabled:opacity-40" onClick={()=>void run(async()=>setRuntime(await setValidationRuntime(pythonPath)))}>检查并使用</button></div><p className="text-xs text-gray-500">也可创建独立 CPU 环境，需要本机 Python（推荐 3.13）及网络下载组件；基础应用仍可独立运行。首次建模缓存官方预训练权重。</p><button disabled={busy || ["running","queued"].includes(runtime?.install_job?.status ?? "")} className="rounded-lg border px-3 py-2 disabled:opacity-40" onClick={()=>void run(async()=>{const job=await installValidationRuntime(runtime?.base_python ?? undefined);setRuntime(r=>r?{...r,install_job:job}:r);window.dispatchEvent(new Event("dataset-manager:jobs-changed"));})}>创建独立 CPU 环境</button>{runtime?.install_job && <a className="ml-3 text-xs underline" target="_blank" rel="noreferrer" href={`/api/validation/runtime/diagnostics/${runtime.install_job.id}`}>安装日志</a>}{runtime?.install_job && <p role="status">{validationStages[runtime.install_job.stage] ?? validationStatus[runtime.install_job.status]}{runtime.install_job.error && ` · ${String(runtime.install_job.error.message ?? "请检查安装日志")}`}</p>}</div></details>
    <section className="space-y-4 rounded-xl border border-line bg-white p-5"><div><h2 className="font-semibold">开始一次验证</h2><p className="mt-1 text-sm text-gray-500">先确认数据范围和目的，再检查实际分组；预览不会写回项目划分。</p></div>{!preparation&&<p role="status" className="text-sm text-gray-500">正在读取项目区域设置与数据范围…</p>}<fieldset disabled={busy||!preparation} className="space-y-4"><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">验证目的<select aria-label="验证目的" className="mt-1 w-full rounded-lg border p-2" value={mode} onChange={e=>{setMode(e.target.value);invalidate();}}><option value="evaluation">独立评估：正常训练 + 独立验证/测试</option><option value="exploration">正常一致性探索：只有正常图片也可开始</option></select></label><label className="text-sm">数据范围<select aria-label="验证数据范围" className="mt-1 w-full rounded-lg border p-2" value={scope} onChange={e=>{setScope(e.target.value);invalidate();}}><option value="all">项目全部图片</option><option value="current" disabled={!context?.currentQuery}>从数据页带来的当前筛选</option><option value="selected" disabled={!context?.selectedIds?.length}>从数据页带来的所选图片（{context?.selectedIds?.length ?? 0}）</option></select></label></div><p className="rounded-lg bg-gray-50 p-3 text-sm">{mode==="evaluation"?"纯正常拟合；验证和测试各需正常、异常独立组。阈值在验证集确定，测试结果待冻结阈值后开启。":"至少两个独立正常工件组，整组分别用于拟合和验证；展示正常分数与误报，不产生异常检出率或正式测试结论。"}</p><label className="block text-sm"><input type="checkbox" checked={independent} onChange={e=>{setIndependent(e.target.checked);invalidate();}} /> 我确认未填写工件组的图片来自独立采集，不含同一工件的多视角或连拍</label><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">基线算法<select aria-label="基线算法" className="mt-1 w-full rounded-lg border p-2" value={model} onChange={e=>{setModel(e.target.value);invalidate();}}><option value="padim">PaDiM · 正常特征分布</option><option value="patchcore">PatchCore · 正常特征库对照</option></select></label><label className="text-sm">实验名称<input aria-label="实验名称" className="mt-1 w-full rounded-lg border p-2" maxLength={160} value={name} onChange={e=>setName(e.target.value)} placeholder="可选，例如首批光照 A" /></label></div><details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">高级设置</summary><label className="mt-3 block text-sm">模型输入尺寸<select className="ml-2 rounded border p-2" value={imageSize} onChange={e=>{setImageSize(Number(e.target.value));invalidate();}}><option value={128}>128 · 更快，可能损失细小缺陷</option><option value={256}>256 · 默认</option><option value={384}>384 · 保留更多细节，耗时更高</option></select></label></details><div className="space-y-3 rounded-lg border p-4"><ValidationRoiEditor value={roi} onChange={value=>{setRoi(value);invalidate();}} references={preparation?.references??[]} disabled={busy||!preparation}/><div className="flex flex-wrap gap-3 text-xs"><button disabled={busy||!preparation} className="underline disabled:opacity-40" onClick={()=>void run(async()=>{if(!preparation)return;setPreparation(await saveValidationRoi(datasetId,roi,preparation.dataset_revision));invalidate();setPreparationNotice("已保存为项目默认区域，下次打开会自动带入。");})}>保存为项目默认区域</button><button disabled={busy} className="underline" onClick={()=>void run(async()=>{const value=await getValidationPreparation(datasetId);setPreparation(value);setRoi(value.roi);invalidate();setPreparationNotice("已恢复项目保存的检测区域。");})}>恢复项目区域设置</button><span className="text-gray-500">仅影响新实验，已有模型保持原区域。</span></div>{preparationNotice&&<p role="status" className="text-xs text-gray-600">{preparationNotice}</p>}</div><button className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white" onClick={()=>void run(async()=>setPlan(await previewValidation(datasetId,{mode,model,roi,image_size:imageSize,protocol:{independent_capture_declared:independent,sample_query:sampleQuery}})))}>{busy?"正在检查数据…":"检查数据与拟合方案"}</button></fieldset>
      {plan && <div className="space-y-3 border-t pt-4"><div className="grid grid-cols-3 gap-2">{Object.entries(counts ?? {}).map(([split,c])=><div key={split} className="rounded-lg bg-gray-50 p-3 text-sm"><strong>{split==="train"?"拟合":split==="val"?"验证":"测试"}</strong><p>正常 {c.normal} / 异常 {c.abnormal}</p></div>)}</div><p className="text-sm text-gray-500">纳入 {String(plan.summary.included_count)} 张，排除 {String(plan.summary.excluded_count)} 张。CPU 单次最多 256 张拟合、2000 张总图片。</p>{(plan.summary.blockers as string[]).map(text=><p role="alert" key={text} className="rounded-lg bg-amber-50 p-2 text-sm text-amber-900">{text}</p>)}<button disabled={busy || !runtime?.ready || plan.summary.blocked!==false} className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-40" onClick={()=>void run(async()=>{await createValidationRun(datasetId,plan,name.trim()||`${model==="padim"?"PaDiM":"PatchCore"} 基线验证`);setPlan(null);await refreshRuns();window.dispatchEvent(new Event("dataset-manager:jobs-changed"));})}>确认输入，运行基线</button>{!runtime?.ready&&<p className="text-sm text-amber-800">数据可先预览；运行前请完成上方可选组件配置。</p>}</div>}
    </section>
    {preparation&&<ValidationQualityPanel datasetId={datasetId} query={sampleQuery} roi={roi}/>}
    <section className="space-y-3 rounded-xl border border-line bg-white p-5"><div className="flex items-center justify-between"><h2 className="font-semibold">验证记录</h2><button className="text-sm text-gray-500 underline" onClick={()=>void run(refreshRuns)}>刷新记录</button></div>{!runs.length&&<p className="py-5 text-sm text-gray-500">还没有实验。完成上方检查后即可建立第一条可追溯的基线。</p>}{runs.map(item=><article key={item.id} className="rounded-lg border border-line p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-medium">{item.name}</h3><p className="mt-1 text-xs text-gray-500">{item.recipe.model} · {item.mode==="evaluation"?"独立评估":item.mode==="batch"?"第二批验证":"正常一致性探索"} · 项目版本 {item.dataset_revision} · {new Date(item.created_at).toLocaleString("zh-CN")}</p></div><span className="text-sm">{validationStatus[item.job?.status ?? ""] ?? "等待任务绑定"}</span></div>{item.job&&<div className="mt-3 flex flex-wrap gap-3 text-sm"><span>{validationStages[item.job.stage]??item.job.stage} · {item.job.progress_current}/{item.job.progress_total??"…"}</span>{["queued","running"].includes(item.job.status)&&<button className="underline" onClick={()=>void run(async()=>{await cancelJob(item.job!.id);await refreshRuns();})}>取消运行</button>}{["failed","cancelled","interrupted"].includes(item.job.status)&&<button className="underline" onClick={()=>void run(async()=>{await retryJob(item.job!.id);await refreshRuns();})}>重试运行</button>}{item.job.status==="succeeded"&&<button className="rounded-lg border px-3 py-1.5" onClick={()=>navigate(`/datasets/${datasetId}/validate/${item.id}`,{state:{...location.state,validationSetup:{mode,model,imageSize,scope,name,roi}}})}>查看本次结果</button>}{item.job.error&&<p role="alert" className="w-full text-red-700">{String(item.job.error.message??"运行失败")}</p>}{!["queued","running"].includes(item.job.status)&&<button className="text-xs text-gray-500 underline" onClick={()=>{if(window.confirm(`删除“${item.name}”的实验记录、模型和结果图片？原图不变；测试图片已被查看的历史仍保留。`))void run(async()=>{await deleteValidationRun(item.id);await refreshRuns();});}}>删除实验记录</button>}<a className="text-xs text-gray-500 underline" href={`/api/validation/runs/${item.id}/diagnostics`} target="_blank" rel="noreferrer">诊断日志</a></div>}</article>)}</section>
    <DirectoryPickerModal open={picker} mode="file" extensions=".exe" onClose={()=>setPicker(false)} onSelect={setPythonPath} />
  </main>;
}
