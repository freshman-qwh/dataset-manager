import json
import math
import os
import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select, delete
from app.core.config import get_settings
from app.models.validation import ValidationRun
from app.models.job import Job
from app.schemas.job import JobCreate
from app.schemas.validation import ValidationRunCreate, ValidationRunRead
from app.services import anomaly_protocol_service as protocol, industrial_plan_service as plans, job_service
from app.services import validation_plan_service, validation_runtime_service as runtime
from app.services.dataset_service import get_dataset_or_404
from app.services.directory_export_job_service import _copy_verified
from app.services.job_runner import JobContext
from app.services.validation_process_service import run_process

JOB_TYPE = "validation.baseline"
WORKER = Path(__file__).resolve().parents[1] / "templates" / "anomaly_worker.py"


def run_root(run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise HTTPException(404, "找不到该验证记录。")
    return get_settings().storage_root / "validation-runs" / run_id


def get_run(session: Session, run_id: str) -> ValidationRun:
    run_root(run_id)
    run = session.get(ValidationRun, run_id)
    if run is None:
        raise HTTPException(404, "找不到该验证记录。")
    return run


def read_contract(run: ValidationRun) -> dict:
    try:
        contract = json.loads((run_root(run.id) / "contract.json").read_text(encoding="utf-8"))
        if plans.digest(contract) != run.contract_sha256:
            raise ValueError("digest")
        return contract
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "实验输入记录缺失或校验失败，请恢复完整备份。") from exc


def read_run(session: Session, run: ValidationRun) -> ValidationRunRead:
    job = job_service.get_job(session, run.job_id) if run.job_id else None
    return ValidationRunRead(id=run.id, dataset_id=run.dataset_id, dataset_revision=run.dataset_revision,
        name=run.name, mode=run.mode, recipe=json.loads(run.recipe_json), parent_run_id=run.parent_run_id,
        job=job, created_at=run.created_at, current_dataset_revision=get_dataset_or_404(session, run.dataset_id).revision,
        summary=json.loads(run.summary_json) if run.summary_json else read_contract(run)["summary"])


def create_run(session: Session, dataset_id: int, payload: ValidationRunCreate) -> ValidationRunRead:
    checked = runtime.status()
    if not checked.ready:
        raise HTTPException(422, checked.message)
    session.commit(); session.exec(text("BEGIN IMMEDIATE"))
    try:
        plan = validation_plan_service.validate(session, dataset_id, payload.plan_id, payload.plan_hash)
        active = job_service.find_active_job(session, job_type=JOB_TYPE, dataset_id=dataset_id,
            parameter_match=("plan_hash", payload.plan_hash))
        if active:
            run = session.exec(select(ValidationRun).where(ValidationRun.job_id == active.id)).first()
            if run:
                session.commit(); return read_run(session, run)
        run_id = uuid4().hex
        contract = {k: v for k, v in plan.items() if k not in {"plan_hash", "confirmation", "expires_at"}}
        contract["run_id"] = run_id
        root = run_root(run_id); root.mkdir(parents=True)
        try:
            (root / "contract.json").write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
            run = ValidationRun(id=run_id, dataset_id=dataset_id, dataset_revision=plan["dataset_revision"],
                plan_id=payload.plan_id, plan_hash=payload.plan_hash, mode=plan["mode"], name=payload.name.strip() or "基线验证",
                recipe_json=json.dumps(plan["recipe"]), summary_json=json.dumps(plan["summary"]), contract_sha256=plans.digest(contract), parent_run_id=plan.get("parent_run_id"))
            session.add(run)
            session.flush()
            # Commit the run and its queue entry together. The generic helper
            # commits independently and is inappropriate inside this transaction.
            job = Job(job_type=JOB_TYPE, dataset_id=dataset_id, title=f"快速验证：{run.name}",
                parameters_json=json.dumps({"run_id": run_id, "plan_hash": payload.plan_hash}))
            session.add(job); session.flush()
            run.job_id = job.id; session.add(run); session.commit()
        except Exception:
            session.rollback()
            if root.exists() and root.parent == get_settings().storage_root / "validation-runs":
                shutil.rmtree(root)
            raise
        return read_run(session, run)
    except Exception:
        session.rollback()
        raise


def load_result(session: Session, run_id: str) -> tuple[ValidationRun, dict, dict]:
    run = get_run(session, run_id)
    job = job_service.get_job(session, run.job_id) if run.job_id else None
    if not job or job.status != "succeeded":
        raise HTTPException(409, "验证尚未完成，请查看任务进度。")
    try:
        artifact_job = int(job.result["artifact_job_id"])
        path = run_root(run.id) / f"attempt-{artifact_job}" / "result.json"
        if protocol.file_digest(path) != job.result["result_sha256"]:
            raise ValueError("checksum")
        result = json.loads(path.read_text(encoding="utf-8"))
        return run, read_contract(run), result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "验证结果文件缺失或校验失败。") from exc


def result_root(session: Session, run: ValidationRun) -> Path:
    job = job_service.get_job(session, run.job_id)
    if job.status != "succeeded" or not job.result:
        raise HTTPException(409, "验证结果尚未完成。")
    return run_root(run.id) / f"attempt-{int(job.result['artifact_job_id'])}"


def delete_run(session: Session, run_id: str) -> None:
    from app.models.validation import ValidationDecision, ValidationReview
    session.commit(); session.exec(text("BEGIN IMMEDIATE"))
    try:
        run = get_run(session, run_id)
        if session.exec(select(ValidationRun.id).where(ValidationRun.parent_run_id == run_id)).first():
            raise HTTPException(409, "此模型仍被新批次引用，请先删除这些批次记录。")
        jobs = session.exec(select(Job).where(Job.job_type == JOB_TYPE, Job.status.in_(["queued", "running"]))).all()
        if any(json.loads(job.parameters_json).get("run_id") == run_id for job in jobs):
            raise HTTPException(409, "此实验仍有任务，请先取消并等待任务结束。")
        root = run_root(run_id).resolve()
        if root.parent != (get_settings().storage_root / "validation-runs").resolve():
            raise HTTPException(409, "结果目录不在应用存储内。")
        session.exec(delete(ValidationReview).where(ValidationReview.run_id == run_id))
        session.exec(delete(ValidationDecision).where(ValidationDecision.run_id == run_id))
        session.delete(run); session.commit()
    except Exception:
        session.rollback(); raise
    # Delete only application-generated model, maps and previews. Raw data never lives here.
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def execute(context: JobContext, parameters: dict[str, object]) -> dict[str, object]:
    execution_started = time.monotonic()
    run_id = str(parameters["run_id"])
    with Session(context.engine) as session:
        run = get_run(session, run_id)
        if run.job_id != context.job_id and run.job_id and job_service.get_job(session, run.job_id).status == "succeeded":
            raise ValueError("此实验已有完整结果，旧失败任务不再覆盖；请创建新实验保留历史。")
        # A generic retry owns a new job while preserving the frozen run identity.
        run.job_id = context.job_id; session.add(run); session.commit()
        contract = read_contract(run)
        if get_dataset_or_404(session, run.dataset_id).revision != run.dataset_revision:
            raise ValueError("项目在预览后发生变化，请重新检查数据并创建实验。")
    checked = runtime.status()
    if not checked.ready:
        raise ValueError(checked.message)
    root = run_root(run_id).resolve()
    work = root / f"attempt-{context.job_id}.part"
    final = root / f"attempt-{context.job_id}"
    if work.exists() or final.exists():
        raise ValueError("此任务已有输出，请从任务中心创建重试任务。")
    work.mkdir()
    rows = [dict(r) for r in contract["rows"] if r["split"]]
    env = runtime.environment()
    last_progress = None
    def tick():
        nonlocal last_progress
        try:
            value = json.loads((work / "progress.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        signature = (value["stage"], int(value["current"]), int(value["total"]))
        if signature != last_progress:
            context.report_progress(stage=signature[0], current=signature[1], total=signature[2])
            last_progress = signature
    try:
        context.report_progress(current=0, total=len(rows), stage="copying_files")
        total_bytes = sum(Path(r["source_absolute_path"]).stat().st_size for r in rows)
        if total_bytes > 2 * 1024**3 or shutil.disk_usage(root).free < total_bytes + 1024**3:
            raise OSError("快速验证需预留图片副本和模型空间；请缩小范围或释放至少 1 GiB 额外空间。")
        for index, row in enumerate(rows, 1):
            extension = Path(row["relative_path"]).suffix.lower()
            row["image_path"] = f"images/{row['sample_id']}{extension}"
            path = work / row["image_path"]; path.parent.mkdir(exist_ok=True)
            with path.open("xb") as output:
                _copy_verified(Path(row["source_absolute_path"]), output, expected_hash=row["sha256"], checkpoint=context.checkpoint)
            context.report_progress(current=index, total=len(rows), stage="copying_files")
        worker_input = dict(rows=rows, recipe=contract["recipe"], weight_cache=str(runtime.root() / "weights"))
        if run.parent_run_id:
            with Session(context.engine) as session:
                parent, _, parent_result = load_result(session, run.parent_run_id)
                origin = result_root(session, parent)
            worker_input["parent_model"] = dict(path=str(origin / "model.pt"), sha256=parent_result["model_sha256"], map_scale=parent_result["map_scale"])
            if parent_result["model_sha256"] != contract["parent_model_sha256"]:
                raise ValueError("原模型与新批次冻结输入不一致。")
        (work / "input.json").write_text(json.dumps(worker_input, ensure_ascii=False), encoding="utf-8")
        context.report_progress(current=0, total=len(rows), stage="loading_algorithm")
        run_process([checked.python_path, "-I", str(WORKER), "--root", str(work)], root / f"worker-{context.job_id}.log", context.checkpoint, cwd=work, env=env, tick=tick)
        result = json.loads((work / "result.json").read_text(encoding="utf-8"))
        if result.get("recipe") != contract["recipe"] or result.get("anomalib") != "2.7.0":
            raise ValueError("算法结果的配方或组件版本与冻结输入不一致。")
        if not run.parent_run_id and protocol.file_digest(work / "model.pt") != result.get("model_sha256"):
            raise ValueError("模型文件校验失败。")
        if run.parent_run_id and (result.get("model_sha256") != contract["parent_model_sha256"] or result.get("map_scale") != parent_result["map_scale"] or result.get("fit_seconds") != 0):
            raise ValueError("新批次未保持原模型、热图标尺或仅推理约束。")
        predicted = {int(r["sample_id"]): float(r["score"]) for r in result["predictions"]}
        if len(predicted) != len(rows) or set(predicted) != {r["sample_id"] for r in rows} or not all(math.isfinite(v) for v in predicted.values()):
            raise ValueError("算法输出的图片集合或分数不完整。")
        for row in rows:
            context.checkpoint()
            if protocol.file_digest(Path(row["source_absolute_path"])) != row["sha256"]:
                raise ValueError("运行过程中原图发生变化，请重新扫描并创建实验。")
            if not (work / "previews" / f"{row['sample_id']}.jpg").is_file() or not (work / "heatmaps" / f"{row['sample_id']}.png").is_file():
                raise ValueError("算法结果缺少图片预览或热图。")
        with Session(context.engine) as session:
            if get_dataset_or_404(session, run.dataset_id).revision != run.dataset_revision:
                raise ValueError("运行过程中项目判定或分组发生变化，请重新检查。")
        result["algorithm_seconds"] = result.get("total_seconds")
        result["total_seconds"] = time.monotonic() - execution_started
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        # Preserve derived previews, maps and model; raw-image backups stay separate.
        shutil.rmtree(work / "images")
        (work / "input.json").unlink()
        context.checkpoint()
        os.rename(work, final)
        return dict(run_id=run_id, artifact_job_id=context.job_id, result_sha256=protocol.file_digest(final / "result.json"),
                    sample_count=len(rows), model=contract["recipe"]["model"])
    finally:
        if work.parent == root and work.exists():
            shutil.rmtree(work, ignore_errors=True)
