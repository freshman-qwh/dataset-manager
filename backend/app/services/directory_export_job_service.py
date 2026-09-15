from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session

from app.schemas.directory_export import (
    DirectoryExportJobCreateRequest,
    DirectoryExportJobCreateResponse,
    DirectoryExportJobParameters,
)
from app.schemas.job import JobCreate
from app.services import (
    dataset_service,
    directory_export_service,
    job_artifact_service,
    job_service,
)
from app.services.job_runner import JobContext


DIRECTORY_EXPORT_JOB_TYPE = "dataset.directory_export"
COPY_CHUNK_SIZE = 1024 * 1024
MANIFEST_FILENAME = "manifest.jsonl"
CONFIG_FILENAME = "export-config.json"
REPORT_FILENAME = "export-report.json"
COMPLETE_MARKER_FILENAME = ".dataset-manager-export.json"


def create_directory_export_job(
    session: Session,
    dataset_id: int,
    payload: DirectoryExportJobCreateRequest,
) -> DirectoryExportJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    plan = directory_export_service.validate_plan_for_job(
        session,
        dataset_id,
        payload.plan_id,
        payload.plan_hash,
    )
    included_count = int(plan["included_count"])
    if included_count <= 0:
        raise directory_export_service.DirectoryExportError(
            "当前计划没有可导出的图片。"
        )
    parameters = DirectoryExportJobParameters(
        plan_id=payload.plan_id,
        plan_hash=payload.plan_hash,
        delivery=str(plan["delivery"]),
        output_name=str(plan["output_name"]),
        included_count=included_count,
        request_fingerprint=payload.plan_hash,
    ).model_dump(mode="json")

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=DIRECTORY_EXPORT_JOB_TYPE,
        dataset_id=dataset_id,
        parameter_match=("request_fingerprint", payload.plan_hash),
    )
    if active is not None:
        session.commit()
        return DirectoryExportJobCreateResponse(job=active, created=False)

    delivery_label = "ZIP" if plan["delivery"] == "zip" else "服务器目录"
    created = job_service.create_job(
        session,
        JobCreate(
            job_type=DIRECTORY_EXPORT_JOB_TYPE,
            title=f"导出分拣{delivery_label}：{dataset.name}",
            dataset_id=dataset_id,
            parameters=parameters,
            progress_total=included_count,
        ),
    )
    return DirectoryExportJobCreateResponse(job=created, created=True)


def run_directory_export_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    try:
        snapshot = DirectoryExportJobParameters.model_validate(parameters)
    except ValidationError as exc:
        raise job_service.JobStateError(
            f"Invalid directory export parameter snapshot: {exc}"
        ) from exc
    plan = directory_export_service.load_directory_export_plan(
        snapshot.plan_id,
        expected_hash=snapshot.plan_hash,
    )
    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
    if job.dataset_id is None or job.dataset_id != int(plan["dataset_id"]):
        raise job_service.JobStateError(
            "A dataset.directory_export job requires the matching dataset_id."
        )

    context.report_progress(
        current=0,
        total=snapshot.included_count,
        stage="copying_files",
    )
    if snapshot.delivery == "zip":
        return _write_zip_export(context, snapshot, plan)
    return _write_directory_export(context, snapshot, plan)


def _write_zip_export(
    context: JobContext,
    snapshot: DirectoryExportJobParameters,
    plan: dict[str, object],
) -> dict[str, object]:
    items = _included_items(plan)
    with job_artifact_service.JobArtifactWorkspace(
        job_artifact_service.job_artifact_root(),
        job_id=context.job_id,
        filename=snapshot.output_name,
        media_type="application/zip",
    ) as workspace:
        with ZipFile(workspace.path, mode="w", compression=ZIP_STORED) as archive:
            copied_bytes = 0
            for index, item in enumerate(items, start=1):
                context.checkpoint()
                source = Path(str(item["source_absolute_path"]))
                target = _zip_target(str(item["target_relative_path"]))
                with archive.open(target, mode="w") as destination:
                    copied_bytes += _copy_verified(
                        source,
                        destination,
                        expected_hash=str(item["file_hash"]),
                        checkpoint=context.checkpoint,
                    )
                context.report_progress(
                    current=index,
                    total=len(items),
                    stage="copying_files",
                )
            manifest, config, report = _metadata_payloads(
                plan,
                copied_bytes=copied_bytes,
                output_kind="zip",
                output_path=snapshot.output_name,
            )
            archive.writestr(MANIFEST_FILENAME, manifest)
            archive.writestr(CONFIG_FILENAME, config)
            archive.writestr(REPORT_FILENAME, report)
        context.report_progress(
            current=len(items),
            total=len(items),
            stage="finalizing",
        )
        metadata = workspace.finalize(checkpoint=context.checkpoint)
        context.checkpoint()
    return {
        "delivery": "zip",
        "plan_id": snapshot.plan_id,
        "plan_hash": snapshot.plan_hash,
        "exported_sample_count": len(items),
        "copied_bytes": copied_bytes,
        "artifact": {
            "filename": metadata.filename,
            "media_type": metadata.media_type,
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
        },
    }


def _write_directory_export(
    context: JobContext,
    snapshot: DirectoryExportJobParameters,
    plan: dict[str, object],
) -> dict[str, object]:
    items = _included_items(plan)
    root = directory_export_service.directory_export_output_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    final_path = (root / snapshot.output_name).resolve()
    if final_path.parent != root:
        raise job_service.JobStateError("Directory export target escaped its root.")
    existing = _existing_directory_result(final_path, snapshot.plan_hash)
    if existing is not None:
        return existing
    if final_path.exists():
        raise FileExistsError("导出目录已经存在，系统不会覆盖或合并。")

    temporary_path = (
        root / f".{snapshot.output_name}.job-{context.job_id}.{uuid4().hex}.part"
    ).resolve()
    if temporary_path.parent != root:
        raise job_service.JobStateError("Directory export workspace escaped its root.")
    temporary_path.mkdir()
    copied_bytes = 0
    try:
        for index, item in enumerate(items, start=1):
            context.checkpoint()
            source = Path(str(item["source_absolute_path"]))
            destination = _directory_target(
                temporary_path,
                str(item["target_relative_path"]),
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                copied_bytes += _copy_verified(
                    source,
                    output,
                    expected_hash=str(item["file_hash"]),
                    checkpoint=context.checkpoint,
                )
            context.report_progress(
                current=index,
                total=len(items),
                stage="copying_files",
            )

        manifest, config, report = _metadata_payloads(
            plan,
            copied_bytes=copied_bytes,
            output_kind="directory",
            output_path=str(final_path),
        )
        (temporary_path / MANIFEST_FILENAME).write_text(manifest, encoding="utf-8")
        (temporary_path / CONFIG_FILENAME).write_text(config, encoding="utf-8")
        (temporary_path / REPORT_FILENAME).write_text(report, encoding="utf-8")
        (temporary_path / COMPLETE_MARKER_FILENAME).write_text(
            json.dumps(
                {
                    "plan_id": snapshot.plan_id,
                    "plan_hash": snapshot.plan_hash,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        context.report_progress(
            current=len(items),
            total=len(items),
            stage="publishing_directory",
        )
        context.checkpoint()
        if final_path.exists():
            raise FileExistsError("导出目录已经存在，系统不会覆盖或合并。")
        os.replace(temporary_path, final_path)
    except BaseException:
        _remove_temporary_directory(temporary_path, root)
        raise

    return {
        "delivery": "directory",
        "plan_id": snapshot.plan_id,
        "plan_hash": snapshot.plan_hash,
        "exported_sample_count": len(items),
        "copied_bytes": copied_bytes,
        "output_path": str(final_path),
        "manifest_path": str(final_path / MANIFEST_FILENAME),
    }


def _included_items(plan: dict[str, object]) -> list[dict[str, object]]:
    items = plan.get("items")
    if not isinstance(items, list):
        raise job_service.JobStateError("Directory export plan is missing items.")
    included = [item for item in items if isinstance(item, dict) and item.get("included")]
    if len(included) != int(plan["included_count"]):
        raise job_service.JobStateError("Directory export plan count does not match its items.")
    return included


def _copy_verified(
    source: Path,
    destination,
    *,
    expected_hash: str,
    checkpoint,
) -> int:
    digest = sha256()
    copied = 0
    try:
        handle = source.open("rb")
    except OSError as exc:
        raise FileNotFoundError(f"源文件不可读取：{source.name}") from exc
    with handle:
        while chunk := handle.read(COPY_CHUNK_SIZE):
            checkpoint()
            destination.write(chunk)
            digest.update(chunk)
            copied += len(chunk)
    if digest.hexdigest() != expected_hash:
        raise directory_export_service.DirectoryExportPlanChangedError(
            f"源文件内容在预检后发生变化：{source.name}"
        )
    return copied


def _metadata_payloads(
    plan: dict[str, object],
    *,
    copied_bytes: int,
    output_kind: str,
    output_path: str,
) -> tuple[str, str, str]:
    items = _included_items(plan)
    manifest_rows = []
    for item in items:
        manifest_rows.append(
            {
                key: value
                for key, value in item.items()
                if key not in {"source_absolute_path", "included", "exclusion_reason"}
            }
        )
    manifest = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in manifest_rows
    )
    config = json.dumps(
        {
            "plan_version": plan["plan_version"],
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "dataset_id": plan["dataset_id"],
            "dataset_revision": plan["dataset_revision"],
            "triage_policy": plan["triage_policy"],
            "request": plan["request"],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    report = json.dumps(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "delivery": output_kind,
            "output": output_path,
            "selected_count": plan["selected_count"],
            "exported_sample_count": len(items),
            "excluded_count": plan["excluded_count"],
            "copied_bytes": copied_bytes,
            "directory_counts": plan["directory_counts"],
            "exclusion_counts": plan["exclusion_counts"],
            "warnings": plan["warnings"],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    return manifest, config, report


def _zip_target(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise job_service.JobStateError("Invalid target path in directory export plan.")
    return path.as_posix()


def _directory_target(root: Path, value: str) -> Path:
    relative = PurePosixPath(_zip_target(value))
    path = (root / Path(*relative.parts)).resolve()
    if root not in path.parents:
        raise job_service.JobStateError("Directory export target escaped its workspace.")
    return path


def _remove_temporary_directory(path: Path, root: Path) -> None:
    resolved = path.resolve()
    if (
        resolved.parent != root
        or not resolved.name.startswith(".")
        or not resolved.name.endswith(".part")
    ):
        raise job_service.JobStateError("Refused to clean an unverified export path.")
    if resolved.exists():
        shutil.rmtree(resolved)


def _existing_directory_result(
    final_path: Path,
    expected_hash: str,
) -> dict[str, object] | None:
    if not final_path.is_dir():
        return None
    marker = final_path / COMPLETE_MARKER_FILENAME
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("plan_hash") != expected_hash:
        return None
    manifest = final_path / MANIFEST_FILENAME
    if not manifest.is_file():
        return None
    exported_count = sum(1 for line in manifest.read_text(encoding="utf-8").splitlines() if line)
    return {
        "delivery": "directory",
        "plan_id": payload.get("plan_id"),
        "plan_hash": expected_hash,
        "exported_sample_count": exported_count,
        "copied_bytes": 0,
        "output_path": str(final_path),
        "manifest_path": str(manifest),
        "recovered_existing_output": True,
    }
