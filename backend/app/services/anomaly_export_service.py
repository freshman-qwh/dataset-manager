"""Publish verified image-level packages using the existing local job worker."""
import csv
import io
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import get_settings
from app.schemas.industrial import AnomalyExportRequest, AnomalyExportResponse
from app.schemas.job import JobCreate
from app.services import anomaly_protocol_service as protocols, job_artifact_service, job_service
from app.services.directory_export_job_service import _copy_verified
from app.services.job_runner import JobContext

JOB_TYPE = "dataset.anomaly_export"
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"


def create_job(session: Session, dataset_id: int, payload: AnomalyExportRequest) -> AnomalyExportResponse:
    job_service.ensure_jobs_schema(session)
    protocols.validate_plan(session, dataset_id, payload.plan_id, payload.plan_hash)
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    try:
        # Recheck under the writer lock so a metadata change cannot race creation.
        protocols.validate_plan(session, dataset_id, payload.plan_id, payload.plan_hash)
        fingerprint = f"{payload.plan_hash}:{payload.delivery}"
        active = job_service.find_active_job(session, job_type=JOB_TYPE, dataset_id=dataset_id,
                                            parameter_match=("fingerprint", fingerprint))
        if active:
            session.commit()
            return AnomalyExportResponse(job=active, created=False)
        created = job_service.create_job(session, JobCreate(job_type=JOB_TYPE,
            title="导出工业异常检测训练包", dataset_id=dataset_id,
            parameters={**payload.model_dump(), "fingerprint": fingerprint}))
        return AnomalyExportResponse(job=created, created=True)
    except Exception:
        session.rollback()
        raise


def _metadata(plan: dict, rows: list[dict], delivery: str) -> dict[str, str]:
    csv_file = io.StringIO(newline="")
    fields = ["sample_id", "image_path", "label_index", "split", "group_id", "capture_group_id", "capture_batch_id", "sha256"]
    writer = csv.DictWriter(csv_file, fieldnames=fields)
    writer.writeheader()
    writer.writerows({k: row[k] for k in fields} for row in rows)
    protocol = {k: plan[k] for k in ("plan_id", "plan_hash", "dataset_id", "dataset_revision", "config", "triage_policy")}
    protocol.update(schema_version=1, task="image_classification", masks_included=False,
                    reader="anomalib==2.7.0", isolation="transitive capture identity and SHA256",
                    independent_validation=True, summary=plan["summary"])
    report = dict(plan_id=plan["plan_id"], delivery=delivery, exported_sample_count=len(rows),
                  counts=plan["summary"]["counts"], excluded_count=plan["summary"]["excluded_count"],
                  files_verified=True, source_files_modified=False, masks_included=False)
    manifest_rows = [{k: v for k, v in row.items() if k != "source_absolute_path"} for row in plan["rows"]]
    readme = """# 工业异常检测图像级训练包

正常训练图在 train/good；验证/测试分为 good 与 defect。samples.csv 是冻结的样本、判定、工件组和划分清单。
protocol.json 记录分拣标准、采集独立声明、比例、排除原因和项目版本。不得用 test 调参，也不要重新随机划分或拆开工件组。
异常图片没有像素掩码也合法；本包不提供像素级训练/指标，不生成伪造掩码。

1. 在独立 Python 环境中安装 requirements-reader.txt；本次读取验收环境为 Windows x64 / Python 3.13 / CPU。
   可复现本次环境：python -m pip install -r requirements-reader-lock-windows.txt --extra-index-url https://download.pytorch.org/whl/cpu
   不在 Dataset Manager 的应用环境内安装训练依赖。
2. python load_anomalib.py --check-only 先检查图片完整性、组隔离和类别覆盖（无需训练框架）。
3. python load_anomalib.py 完整读取三个集合。成功应打印 split_preserved: true 及各组数量。
4. 算法代码中：from load_anomalib import create_datamodule；使用 create_datamodule(本包目录)。
   读取器显式提供 train/val/test，禁用 Anomalib 自动重分。更换版本后需要重新做完整读取验证。

在任意工作目录运行时，可使用读取脚本的绝对路径，或 --root 指向本包。可将本包移动到中文或空格路径。
软件负责本地数据准备；此包的通过读取不表示模型效果、产线准确率或像素级协议已通过验收。
"""
    return {"samples.csv": csv_file.getvalue(),
            "manifest.jsonl": "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest_rows),
            "protocol.json": json.dumps(protocol, ensure_ascii=False, indent=2),
            "export-report.json": json.dumps(report, ensure_ascii=False, indent=2),
            "README.md": readme,
            "load_anomalib.py": (TEMPLATE_ROOT / "anomaly_reader.py").read_text(encoding="utf-8"),
            "requirements-reader.txt": (TEMPLATE_ROOT / "reader-requirements.txt").read_text(encoding="utf-8"),
            "requirements-reader-lock-windows.txt": (TEMPLATE_ROOT / "reader-requirements-lock-windows.txt").read_text(encoding="utf-8")}


def _fresh(context: JobContext, dataset_id: int, request: AnomalyExportRequest) -> dict:
    context.checkpoint()
    with Session(context.engine) as session:
        return protocols.validate_plan(session, dataset_id, request.plan_id, request.plan_hash)


def run_export(context: JobContext, parameters: dict[str, object]) -> dict[str, object]:
    request = AnomalyExportRequest.model_validate({k: parameters[k] for k in ("plan_id", "plan_hash", "delivery")})
    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id is None:
            raise ValueError("Industrial export requires a dataset.")
        dataset_id = job.dataset_id
    plan = _fresh(context, dataset_id, request)
    rows = [dict(row) for row in plan["rows"] if row["split"]]
    for row in rows:
        extension = Path(row["relative_path"]).suffix.lower()
        if not extension or len(extension) > 12 or not extension[1:].isalnum():
            raise ValueError("Invalid image extension in plan.")
        row["image_path"] = f"{row['split']}/{'good' if row['label_index'] == 0 else 'defect'}/{row['sample_id']}{extension}"
    metadata_files = _metadata(plan, rows, request.delivery)
    context.report_progress(current=0, total=len(rows), stage="copying_files")
    if request.delivery == "zip":
        filename = f"industrial-{dataset_id}-{context.job_id}.zip"
        with job_artifact_service.JobArtifactWorkspace(job_artifact_service.job_artifact_root(),
            job_id=context.job_id, filename=filename, media_type="application/zip") as workspace:
            copied_sizes: dict[str, int] = {}
            with ZipFile(workspace.path, "w", compression=ZIP_STORED, allowZip64=True) as archive:
                for index, row in enumerate(rows, 1):
                    with archive.open(row["image_path"], "w", force_zip64=True) as output:
                        copied_sizes[row["image_path"]] = _copy_verified(Path(row["source_absolute_path"]), output, expected_hash=row["sha256"], checkpoint=context.checkpoint)
                    context.report_progress(current=index, total=len(rows), stage="copying_files")
                for name, content in metadata_files.items():
                    archive.writestr(name, content.encode("utf-8"))
            # Copying already checks image content in the same read. Check only
            # the archive index here; finalize computes the whole-package hash.
            with ZipFile(workspace.path) as archive:
                entries = archive.infolist()
                expected_names = set(copied_sizes) | set(metadata_files)
                if len(entries) != len(expected_names) or {entry.filename for entry in entries} != expected_names:
                    raise ValueError("Exported package file list does not match the plan.")
                if any(archive.getinfo(name).file_size != size for name, size in copied_sizes.items()):
                    raise ValueError("Exported image size mismatch.")
            _fresh(context, dataset_id, request)
            artifact = workspace.finalize(checkpoint=context.checkpoint)
            context.checkpoint()
        return dict(delivery="zip", exported_sample_count=len(rows), plan_id=request.plan_id,
                    artifact=dict(filename=artifact.filename, media_type=artifact.media_type,
                                  size_bytes=artifact.size_bytes, sha256=artifact.sha256))
    root = (get_settings().storage_root / "anomaly-exports").resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / f"industrial-{dataset_id}-{context.job_id}").resolve()
    temporary = (root / f".industrial-{context.job_id}-{uuid4().hex}.part").resolve()
    if target.parent != root or temporary.parent != root or target.exists():
        raise FileExistsError("导出目录已存在或路径不合法，不会覆盖。")
    temporary.mkdir()
    try:
        for index, row in enumerate(rows, 1):
            destination = temporary / row["image_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                copied_size = _copy_verified(Path(row["source_absolute_path"]), output, expected_hash=row["sha256"], checkpoint=context.checkpoint)
            if destination.stat().st_size != copied_size:
                raise ValueError("Exported image size mismatch.")
            context.report_progress(current=index, total=len(rows), stage="copying_files")
        for name, content in metadata_files.items():
            (temporary / name).write_text(content, encoding="utf-8")
        _fresh(context, dataset_id, request)
        os.rename(temporary, target)
    finally:
        if temporary.parent == root and temporary.exists():
            shutil.rmtree(temporary)
    return dict(delivery="directory", output_path=str(target), exported_sample_count=len(rows), plan_id=request.plan_id)
