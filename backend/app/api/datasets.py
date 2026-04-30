from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.dataset import DatasetCreate, DatasetRead, DatasetUpdate
from app.schemas.duplicates import DuplicateReport
from app.schemas.export_template import ExportTemplateResponse
from app.schemas.metadata_import import MetadataImportRequest, MetadataImportResult
from app.schemas.sample import BatchSampleUpdate, BatchSampleUpdateResult, SampleListResponse
from app.schemas.scan import ScanRequest, ScanResult
from app.schemas.stats import DatasetStats
from app.schemas.tag import TagCreate, TagRead
from app.services import (
    dataset_service,
    duplicate_service,
    export_template_service,
    manifest_service,
    metadata_import_service,
    sample_service,
    scan_service,
    stats_service,
    tag_service,
)

router = APIRouter(prefix="/api", tags=["datasets"])


@router.get("/datasets", response_model=list[DatasetRead])
def list_datasets(session: Session = Depends(get_session)) -> list[DatasetRead]:
    return dataset_service.list_datasets(session)


@router.post("/datasets", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: DatasetCreate,
    session: Session = Depends(get_session),
) -> DatasetRead:
    return dataset_service.create_dataset(session, payload)


@router.get("/datasets/{dataset_id}", response_model=DatasetRead)
def get_dataset(dataset_id: int, session: Session = Depends(get_session)) -> DatasetRead:
    return dataset_service.get_dataset(session, dataset_id)


@router.patch("/datasets/{dataset_id}", response_model=DatasetRead)
def update_dataset(
    dataset_id: int,
    payload: DatasetUpdate,
    session: Session = Depends(get_session),
) -> DatasetRead:
    return dataset_service.update_dataset(session, dataset_id, payload)


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: int, session: Session = Depends(get_session)) -> Response:
    dataset_service.delete_dataset(session, dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/datasets/{dataset_id}/scan", response_model=ScanResult)
def scan_dataset(
    dataset_id: int,
    payload: ScanRequest,
    session: Session = Depends(get_session),
) -> ScanResult:
    return scan_service.scan_dataset(session, dataset_id, payload)


@router.get("/datasets/{dataset_id}/samples", response_model=SampleListResponse)
def list_dataset_samples(
    dataset_id: int,
    search: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    split: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=60, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_session),
) -> SampleListResponse:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return sample_service.list_samples(
        session,
        dataset_id,
        search,
        file_type,
        tag,
        split,
        page,
        page_size,
        sort_by,
        sort_order,
    )


@router.patch("/datasets/{dataset_id}/samples/batch", response_model=BatchSampleUpdateResult)
def batch_update_dataset_samples(
    dataset_id: int,
    payload: BatchSampleUpdate,
    session: Session = Depends(get_session),
) -> BatchSampleUpdateResult:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return sample_service.batch_update_samples(session, dataset_id, payload)


@router.get("/datasets/{dataset_id}/duplicates", response_model=DuplicateReport)
def dataset_duplicates(dataset_id: int, session: Session = Depends(get_session)) -> DuplicateReport:
    return duplicate_service.get_duplicate_report(session, dataset_id)


@router.get("/datasets/{dataset_id}/tags", response_model=list[TagRead])
def list_dataset_tags(dataset_id: int, session: Session = Depends(get_session)) -> list[TagRead]:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return tag_service.list_tags(session, dataset_id)


@router.post("/datasets/{dataset_id}/tags", response_model=TagRead, status_code=status.HTTP_201_CREATED)
def create_dataset_tag(
    dataset_id: int,
    payload: TagCreate,
    session: Session = Depends(get_session),
) -> TagRead:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return tag_service.create_tag(session, dataset_id, payload)


@router.post("/datasets/{dataset_id}/import-metadata", response_model=MetadataImportResult)
def import_dataset_metadata(
    dataset_id: int,
    payload: MetadataImportRequest,
    session: Session = Depends(get_session),
) -> MetadataImportResult:
    return metadata_import_service.import_metadata(session, dataset_id, payload)


@router.get("/stats/datasets/{dataset_id}", response_model=DatasetStats)
def dataset_stats(dataset_id: int, session: Session = Depends(get_session)) -> DatasetStats:
    return stats_service.get_dataset_stats(session, dataset_id)


@router.get("/datasets/{dataset_id}/export-manifest")
def export_dataset_manifest(
    dataset_id: int,
    search: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    split: str | None = Query(default=None),
    sample_ids: list[int] | None = Query(default=None),
    sort_by: str = Query(default="relative_path"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_session),
) -> dict:
    return manifest_service.export_manifest(
        session,
        dataset_id,
        search=search,
        file_type=file_type,
        tag=tag,
        split=split,
        sample_ids=sample_ids,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/datasets/{dataset_id}/export-template", response_model=ExportTemplateResponse)
def export_dataset_template(
    dataset_id: int,
    format: str = Query(default="csv"),
    session: Session = Depends(get_session),
) -> ExportTemplateResponse:
    return export_template_service.export_template(session, dataset_id, format)
