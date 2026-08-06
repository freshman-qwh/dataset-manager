from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.job_runtime import job_runner
from app.schemas.annotation_import import (
    LabelmeImportJobCreateRequest,
    LabelmeImportJobCreateResponse,
    LabelmeImportRequest,
    LabelmeImportResult,
)
from app.schemas.annotation_export import (
    AnnotationExportFormat,
    AnnotationExportJobCreateRequest,
    AnnotationExportJobCreateResponse,
    AnnotationExportPrecheckRequest,
    AnnotationExportPrecheckResponse,
)
from app.services import (
    annotation_export_job_service,
    annotation_export_precheck_service,
    annotation_export_service,
    annotation_import_service,
    annotation_import_job_service,
    job_service,
)

router = APIRouter(prefix="/api", tags=["annotation-exports"])


@router.post(
    "/datasets/{dataset_id}/annotation-export-precheck",
    response_model=AnnotationExportPrecheckResponse,
)
def precheck_annotation_export(
    dataset_id: int,
    payload: AnnotationExportPrecheckRequest,
    session: Session = Depends(get_session),
) -> AnnotationExportPrecheckResponse:
    return annotation_export_precheck_service.precheck_annotation_export(session, dataset_id, payload)


@router.post("/datasets/{dataset_id}/annotations/import-labelme", response_model=LabelmeImportResult)
def import_labelme_annotations(
    dataset_id: int,
    payload: LabelmeImportRequest,
    session: Session = Depends(get_session),
) -> LabelmeImportResult:
    return annotation_import_service.import_labelme_annotations(session, dataset_id, payload)


@router.post(
    "/datasets/{dataset_id}/annotation-import-labelme-jobs",
    response_model=LabelmeImportJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_labelme_import_job(
    dataset_id: int,
    payload: LabelmeImportJobCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> LabelmeImportJobCreateResponse:
    try:
        result = annotation_import_job_service.create_labelme_import_job(session, dataset_id, payload)
    except job_service.JobSchemaUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except job_service.JobError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result


@router.post(
    "/datasets/{dataset_id}/annotation-export-jobs",
    response_model=AnnotationExportJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation_export_job(
    dataset_id: int,
    payload: AnnotationExportJobCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> AnnotationExportJobCreateResponse:
    try:
        result = annotation_export_job_service.create_annotation_export_job(
            session,
            dataset_id,
            payload,
        )
    except job_service.JobSchemaUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except annotation_export_service.AnnotationExportBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "ANNOTATION_EXPORT_BLOCKED",
                "precheck": exc.precheck.model_dump(mode="json"),
            },
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result


@router.get("/datasets/{dataset_id}/annotation-export")
def export_annotations(
    dataset_id: int,
    format: AnnotationExportFormat = Query(default="labelme"),
    search: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    file_status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    split: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    sample_ids: list[int] | None = Query(default=None),
    include_empty: bool = Query(default=False),
    sort_by: str = Query(default="relative_path"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_session),
) -> Response:
    try:
        artifact = annotation_export_service.export_annotations(
            session,
            dataset_id,
            format,
            search=search,
            file_type=file_type,
            file_status=file_status,
            tag=tag,
            split=split,
            review_status=review_status,
            sample_ids=sample_ids,
            include_empty=include_empty,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except annotation_export_service.AnnotationExportBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "ANNOTATION_EXPORT_BLOCKED",
                "precheck": exc.precheck.model_dump(mode="json"),
            },
        ) from exc
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
