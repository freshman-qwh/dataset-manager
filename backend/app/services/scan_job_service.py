from __future__ import annotations

import json

from sqlalchemy import text
from sqlmodel import Session

from app.models.job import Job
from app.schemas.scan import ScanJobCreateResponse, ScanRequest
from app.services import dataset_service, job_service, scan_service
from app.services.job_runner import JobCancelled, JobContext, JobInterrupted


SCAN_JOB_TYPE = "dataset.scan"


def create_scan_job(
    session: Session,
    dataset_id: int,
    payload: ScanRequest,
) -> ScanJobCreateResponse:
    root = scan_service.resolve_scan_root(session, dataset_id, payload)
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=SCAN_JOB_TYPE,
        dataset_id=dataset_id,
    )
    if active is not None:
        session.commit()
        return ScanJobCreateResponse(job=active, created=False)

    batch = scan_service.prepare_scan_batch(session, dataset_id, payload)
    frozen_parameters: dict[str, object] = {"folder_path": str(root)}
    if payload.import_format != "auto":
        frozen_parameters["import_format"] = payload.import_format
    if payload.recognize_existing:
        frozen_parameters["recognize_existing"] = True
    if batch is not None:
        frozen_parameters["batch_id"] = batch.id

    # Schema/dataset checks ran before BEGIN IMMEDIATE. Commit the batch and
    # queued job together, without opening another schema-inspection connection
    # inside this transaction (notably important with SQLite StaticPool).
    job = Job(
        job_type=SCAN_JOB_TYPE,
        title=f"扫描数据集：{dataset.name}",
        dataset_id=dataset_id,
        parameters_json=json.dumps(frozen_parameters, ensure_ascii=False),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return ScanJobCreateResponse(job=job_service.to_job_read(job), created=True)


def run_scan_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id is None:
            raise job_service.JobStateError("A dataset.scan job requires dataset_id.")
        folder_path = parameters.get("folder_path")
        if not isinstance(folder_path, str) or not folder_path:
            raise job_service.JobStateError(
                "A dataset.scan job requires a frozen folder_path."
            )

        try:
            result = scan_service.scan_dataset(
                session,
                job.dataset_id,
                ScanRequest.model_validate(parameters),
                checkpoint=context.checkpoint,
                progress=lambda stage, current, total, error_count: (
                    context.report_progress(
                        current=current,
                        total=total,
                        stage=stage,
                        error_count=error_count,
                    )
                ),
            )
        except scan_service.ScanStopped as stopped:
            partial_result = stopped.result.model_dump(mode="json")
            if isinstance(stopped.__cause__, JobCancelled):
                raise JobCancelled(
                    str(stopped.__cause__),
                    result=partial_result,
                ) from stopped
            if isinstance(stopped.__cause__, JobInterrupted):
                raise JobInterrupted(
                    str(stopped.__cause__),
                    result=partial_result,
                ) from stopped
            raise
    return result.model_dump(mode="json")
