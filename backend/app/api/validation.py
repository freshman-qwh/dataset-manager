from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.validation import ValidationRun
from app.schemas.industrial import FrozenPlanRead
from app.schemas.job import JobRead
from app.schemas.validation import RuntimeConfigure, RuntimeInstall, RuntimeRead, ValidationPreviewRequest, ValidationRunCreate, ValidationRunRead
from app.schemas.validation import ThresholdRequest
from app.services import industrial_plan_service as plans
from app.services import validation_plan_service, validation_run_service as runs, validation_runtime_service as runtime
from app.services.dataset_service import get_dataset_or_404

router = APIRouter(prefix="/api", tags=["validation"])


@router.get("/validation/runtime", response_model=RuntimeRead)
def runtime_status(session: Session = Depends(get_session)):
    return runtime.status(session)


@router.put("/validation/runtime", response_model=RuntimeRead)
def configure_runtime(payload: RuntimeConfigure):
    return runtime.configure(payload.python_path)


@router.post("/validation/runtime/install-jobs", response_model=JobRead)
def install_runtime(payload: RuntimeInstall, session: Session = Depends(get_session)):
    from app.core.job_runtime import job_runner
    job = runtime.create_install(session, payload.base_python)
    job_runner.notify()
    return job


@router.get("/validation/runtime/diagnostics/{job_id}")
def runtime_diagnostics(job_id: int, session: Session = Depends(get_session)):
    from fastapi.responses import PlainTextResponse
    from app.services import job_service
    job = job_service.get_job(session, job_id)
    if job.job_type != runtime.JOB_TYPE:
        raise HTTPException(404, "不是组件安装任务。")
    path = runtime.root() / f"install-{job_id}.log"
    if not path.is_file():
        raise HTTPException(404, "尚无安装日志。")
    with path.open("rb") as file:
        file.seek(max(0, path.stat().st_size - 100000))
        return PlainTextResponse(file.read().decode("utf-8", errors="replace"))


@router.post("/datasets/{dataset_id}/validation/previews", response_model=FrozenPlanRead)
def preview_validation(dataset_id: int, payload: ValidationPreviewRequest, session: Session = Depends(get_session)):
    return plans.page(validation_plan_service.preview(session, dataset_id, payload))


@router.post("/datasets/{dataset_id}/validation/runs", response_model=ValidationRunRead)
def create_validation(dataset_id: int, payload: ValidationRunCreate, session: Session = Depends(get_session)):
    from app.core.job_runtime import job_runner
    run = runs.create_run(session, dataset_id, payload)
    job_runner.notify()
    return run


@router.get("/datasets/{dataset_id}/validation/runs", response_model=list[ValidationRunRead])
def list_validation(dataset_id: int, session: Session = Depends(get_session)):
    get_dataset_or_404(session, dataset_id)
    items = session.exec(select(ValidationRun).where(ValidationRun.dataset_id == dataset_id).order_by(ValidationRun.created_at.desc()).limit(100)).all()
    return [runs.read_run(session, run) for run in items]


@router.get("/validation/runs/{run_id}", response_model=ValidationRunRead)
def get_validation(run_id: str, session: Session = Depends(get_session)):
    return runs.read_run(session, runs.get_run(session, run_id))


@router.get("/validation/runs/{run_id}/diagnostics")
def read_diagnostics(run_id: str, session: Session = Depends(get_session)):
    from fastapi.responses import PlainTextResponse
    run = runs.get_run(session, run_id)
    path = runs.run_root(run_id) / f"worker-{run.job_id}.log"
    if not path.is_file():
        raise HTTPException(404, "尚无算法诊断日志。")
    with path.open("rb") as file:
        file.seek(max(0, path.stat().st_size - 100000))
        return PlainTextResponse(file.read().decode("utf-8", errors="replace"))


@router.get("/validation/runs/{run_id}/results")
def read_results(run_id: str, threshold: float | None = Query(None, allow_inf_nan=False), session: Session = Depends(get_session)):
    from app.services.validation_result_service import overview
    return overview(session, run_id, threshold)


@router.get("/validation/runs/{run_id}/predictions")
def read_predictions(run_id: str, split: Literal["train", "val", "test", "batch"] = "val",
    category: Literal["all", "false_positive", "false_negative", "correct_normal", "correct_abnormal", "truth_normal", "truth_abnormal", "unknown", "near_threshold"] = "all",
    threshold: float | None = Query(None, allow_inf_nan=False), page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), session: Session = Depends(get_session)):
    from app.services.validation_result_service import rows_page
    return rows_page(session, run_id, split=split, category=category, threshold=threshold, page=page, page_size=page_size)


@router.post("/validation/runs/{run_id}/freeze-threshold")
def freeze_threshold(run_id: str, payload: ThresholdRequest, session: Session = Depends(get_session)):
    from app.services.validation_result_service import freeze_decision
    return freeze_decision(session, run_id, payload.threshold)


@router.get("/validation/runs/{run_id}/images/{sample_id}")
def result_image(run_id: str, sample_id: int, kind: Literal["preview", "heatmap"] = "preview", session: Session = Depends(get_session)):
    from fastapi.responses import FileResponse
    from app.services.validation_result_service import image_path
    return FileResponse(image_path(session, run_id, sample_id, kind))


@router.get("/validation/runs/{run_id}/report")
def download_report(run_id: str, session: Session = Depends(get_session)):
    from fastapi.responses import JSONResponse
    from app.services.validation_result_service import overview, joined_rows
    run, contract, result = runs.load_result(session, run_id)
    summary = overview(session, run_id)
    rows = joined_rows(contract, result)
    if summary["test_locked"]:
        rows = [row for row in rows if row["split"] != "test"]
    return JSONResponse(dict(schema_version=1, run=summary, predictions=rows, model_sha256=result["model_sha256"],
        masks_included=False, pixel_metrics=None), headers={"Content-Disposition": f'attachment; filename="validation-{run_id}.json"'})
