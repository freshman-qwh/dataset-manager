from __future__ import annotations

from hashlib import sha256
import json

from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session

from app.schemas.annotation_export import (
    AnnotationExportJobCreateRequest,
    AnnotationExportJobCreateResponse,
    AnnotationExportJobParameters,
    AnnotationExportPrecheckRequest,
)
from app.schemas.job import JobCreate
from app.services import (
    annotation_export_precheck_service,
    annotation_export_service,
    dataset_service,
    job_artifact_service,
    job_service,
)
from app.services.job_runner import JobContext


ANNOTATION_EXPORT_JOB_TYPE = "annotation.export"
FORMAT_TITLE = {
    "labelme": "LabelMe",
    "coco_detection": "COCO detection",
    "coco_segmentation": "COCO segmentation",
}


def create_annotation_export_job(
    session: Session,
    dataset_id: int,
    payload: AnnotationExportJobCreateRequest,
) -> AnnotationExportJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    precheck_request = AnnotationExportPrecheckRequest(
        format=payload.format,
        sample_query=payload.sample_query,
        include_empty=payload.include_empty,
    )
    precheck = annotation_export_precheck_service.precheck_annotation_export(
        session,
        dataset_id,
        precheck_request,
    )
    if precheck.blocked:
        raise annotation_export_service.AnnotationExportBlockedError(precheck)

    request_payload = payload.model_dump(mode="json")
    request_fingerprint = sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    parameters = AnnotationExportJobParameters(
        **request_payload,
        class_map=precheck.class_map,
        precheck_summary={
            "sample_count": precheck.sample_count,
            "exportable_object_count": precheck.exportable_object_count,
            "warning_count": precheck.warning_count,
            "info_count": precheck.info_count,
        },
        request_fingerprint=request_fingerprint,
    ).model_dump(mode="json")

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=ANNOTATION_EXPORT_JOB_TYPE,
        dataset_id=dataset_id,
        parameter_match=("request_fingerprint", request_fingerprint),
    )
    if active is not None:
        session.commit()
        return AnnotationExportJobCreateResponse(job=active, created=False)

    created = job_service.create_job(
        session,
        JobCreate(
            job_type=ANNOTATION_EXPORT_JOB_TYPE,
            title=f"导出 {FORMAT_TITLE[payload.format]}：{dataset.name}",
            dataset_id=dataset_id,
            parameters=parameters,
            progress_total=precheck.sample_count,
        ),
    )
    return AnnotationExportJobCreateResponse(job=created, created=True)


def run_annotation_export_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    try:
        snapshot = AnnotationExportJobParameters.model_validate(parameters)
    except ValidationError as exc:
        raise job_service.JobStateError(
            f"Invalid annotation export parameter snapshot: {exc}"
        ) from exc

    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id is None:
            raise job_service.JobStateError(
                "An annotation.export job requires dataset_id."
            )
        context.report_progress(current=0, stage="prechecking")
        artifact_spec = annotation_export_service.annotation_export_artifact_spec(
            job.dataset_id,
            snapshot.format,
        )
        with job_artifact_service.JobArtifactWorkspace(
            job_artifact_service.job_artifact_root(),
            job_id=context.job_id,
            filename=artifact_spec.filename,
            media_type=artifact_spec.media_type,
        ) as workspace:
            exported = annotation_export_service.export_annotations_to_path(
                session,
                job.dataset_id,
                snapshot.format,
                workspace.path,
                query=snapshot.sample_query,
                include_empty=snapshot.include_empty,
                checkpoint=context.checkpoint,
                progress=lambda current, total: context.report_progress(
                    current=current,
                    total=total,
                    stage=(
                        "writing_archive"
                        if snapshot.format == "labelme"
                        else "writing_json"
                    ),
                ),
            )
            exported_sample_count = int(
                exported.report.get("exported_sample_count", 0)
            )
            context.report_progress(
                current=exported_sample_count,
                total=exported_sample_count,
                stage="finalizing",
            )
            metadata = workspace.finalize(checkpoint=context.checkpoint)
            context.checkpoint()

    return {
        "format": snapshot.format,
        "artifact": {
            "filename": metadata.filename,
            "media_type": metadata.media_type,
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
        },
        "exported_sample_count": exported_sample_count,
        "exported_object_count": int(
            exported.report.get("exported_object_count", 0)
        ),
        "warning_count": exported.precheck.warning_count,
        "info_count": exported.precheck.info_count,
        "request_fingerprint": snapshot.request_fingerprint,
    }
