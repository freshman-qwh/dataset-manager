from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.annotation_import import LabelmeImportRequest, LabelmeImportResult
from app.schemas.annotation_export import AnnotationExportPrecheckRequest, AnnotationExportPrecheckResponse
from app.services import annotation_export_precheck_service, annotation_export_service, annotation_import_service

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


@router.get("/datasets/{dataset_id}/annotation-export")
def export_annotations(
    dataset_id: int,
    format: str = Query(default="labelme", pattern="^labelme$"),
    search: str | None = Query(default=None),
    file_status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    split: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    sample_ids: list[int] | None = Query(default=None),
    include_empty: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> Response:
    content = annotation_export_service.export_labelme_zip(
        session,
        dataset_id,
        search=search,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        sample_ids=sample_ids,
        include_empty=include_empty,
    )
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="dataset-{dataset_id}-{format}-annotations.zip"'},
    )
