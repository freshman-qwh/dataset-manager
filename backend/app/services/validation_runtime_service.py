import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session
from app.core.config import get_settings
from app.schemas.job import JobCreate
from app.schemas.validation import RuntimeRead
from app.services import job_service
from app.services.job_runner import JobContext
from app.services.validation_process_service import run_process

JOB_TYPE = "validation.runtime_install"
REQUIREMENTS = Path(__file__).resolve().parents[1] / "templates" / "reader-requirements-lock-windows.txt"


def root() -> Path:
    return get_settings().storage_root / "validation-runtime"


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None); env.pop("PYTHONHOME", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def base_python() -> str | None:
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python")


def probe(path: str) -> RuntimeRead:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        return RuntimeRead(ready=False, python_path=str(candidate), message="找不到此 Python 解释器。", base_python=base_python())
    code = "import json,sys;from importlib.metadata import version;print(json.dumps({'python':sys.version.split()[0],'anomalib':version('anomalib'),'torch':version('torch'),'torchvision':version('torchvision')}))"
    try:
        result = subprocess.run([str(candidate), "-I", "-c", code], capture_output=True, encoding="utf-8", errors="replace",
            timeout=25, env=environment(), creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        versions = json.loads(result.stdout.strip())
        ready = result.returncode == 0 and versions["anomalib"] == "2.7.0" and tuple(int(v) for v in versions["torch"].split("+")[0].split(".")[:2]) >= (2, 10)
        return RuntimeRead(ready=ready, python_path=str(candidate), versions=versions, base_python=base_python(),
            message="独立 CPU 验证环境可用。首次建模会缓存约 45 MB 官方预训练权重。" if ready else "需要 Anomalib 2.7.0 与 PyTorch 2.10 或更新兼容版本，请选择匹配环境或创建 CPU 环境。")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return RuntimeRead(ready=False, python_path=str(candidate), base_python=base_python(), message="此解释器未就绪。可选择已有 Anomalib 2.7.0 环境，或创建独立 CPU 环境。")


def configure(path: str) -> RuntimeRead:
    status = probe(path)
    if not status.ready:
        raise HTTPException(422, status.message)
    folder = root(); folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f"runtime-{uuid4().hex}.tmp"
    temporary.write_text(status.model_dump_json(), encoding="utf-8")
    os.replace(temporary, folder / "runtime.json")
    return status


def status(session: Session | None = None) -> RuntimeRead:
    try:
        saved = json.loads((root() / "runtime.json").read_text(encoding="utf-8"))
        path = saved["python_path"]
    except (OSError, ValueError, KeyError):
        path = os.getenv("DATASET_MANAGER_ALGORITHM_PYTHON")
    result = probe(path) if path else RuntimeRead(ready=False, base_python=base_python(), message="快速验证是可选组件。选择已有环境，或安装独立 CPU 组件；整理与导出无需安装。")
    if session is not None:
        latest = job_service.list_jobs(session, job_type=JOB_TYPE, limit=1).items
        result.install_job = latest[0] if latest else None
    return result


def create_install(session: Session, requested_python: str | None):
    path = requested_python or base_python()
    if not path or not Path(path).is_file():
        raise HTTPException(422, "未找到可用 Python。请安装 Python 3.13，或选择已有算法环境。")
    active = job_service.find_active_job(session, job_type=JOB_TYPE, dataset_id=None)
    if active:
        return active
    return job_service.create_job(session, JobCreate(job_type=JOB_TYPE, title="创建独立 CPU 验证环境", parameters={"base_python": path}))


def install(context: JobContext, parameters: dict[str, object]) -> dict[str, object]:
    folder = root().resolve(); folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"cpu-{uuid4().hex}"
    log = folder / f"install-{context.job_id}.log"
    context.report_progress(current=0, total=3, stage="creating_runtime")
    try:
        run_process([str(parameters["base_python"]), "-I", "-m", "venv", str(target)], log, context.checkpoint, env=environment(), timeout=180)
        python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        context.report_progress(current=1, total=3, stage="installing_runtime")
        run_process([str(python), "-I", "-m", "pip", "install", "-r", str(REQUIREMENTS), "--extra-index-url", "https://download.pytorch.org/whl/cpu", "--prefer-binary", "--disable-pip-version-check"], log, context.checkpoint, env=environment())
        context.report_progress(current=2, total=3, stage="checking_runtime")
        checked = configure(str(python))
        return {"python_path": checked.python_path, "ready": True}
    except Exception:
        if target.resolve().parent == folder and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
