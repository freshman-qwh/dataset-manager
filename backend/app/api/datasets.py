from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.dataset import DatasetCreate, DatasetRead, DatasetUpdate
from app.schemas.duplicates import DuplicateReport
from app.schemas.export_template import ExportTemplateResponse
from app.schemas.metadata_import import MetadataImportRequest, MetadataImportResult
from app.schemas.quality import DatasetQualityReport
from app.schemas.sample import (
    BatchSampleDelete,
    BatchSampleUpdate,
    BatchSampleUpdateResult,
    MissingSampleRepairRequest,
    MissingSampleRepairResult,
    SampleDeleteResult,
    SampleListResponse,
    SampleNavigationResponse,
)
from app.schemas.scan import ScanRequest, ScanResult
from app.schemas.split import SplitPlanRequest, SplitPlanResult
from app.schemas.stats import DatasetStats
from app.schemas.tag import TagCreate, TagRead
from app.schemas.training_readiness import (
    TrainingReadinessConfig,
    TrainingReadinessConfigRequest,
    TrainingReadinessReport,
)
from app.services import (
    dataset_service,
    duplicate_service,
    export_template_service,
    manifest_service,
    metadata_import_service,
    quality_service,
    sample_service,
    scan_service,
    split_service,
    stats_service,
    tag_service,
    training_readiness_service,
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
    file_status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    split: str | None = Query(default=None),
    review_status: str | None = Query(default=None, pattern="^(not_reviewed|in_review|approved|rejected)$"),
    annotation_progress: str | None = Query(
        default=None,
        pattern="^(not_started|in_progress|completed_empty|completed_with_objects)$",
    ),
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
        file_status,
        tag,
        split,
        review_status,
        annotation_progress,
        page,
        page_size,
        sort_by,
        sort_order,
    )


@router.get("/datasets/{dataset_id}/samples/navigation", response_model=SampleNavigationResponse)
def dataset_sample_navigation(
    dataset_id: int,
    sample_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    file_status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    split: str | None = Query(default=None),
    review_status: str | None = Query(default=None, pattern="^(not_reviewed|in_review|approved|rejected)$"),
    annotation_progress: str | None = Query(
        default=None,
        pattern="^(not_started|in_progress|completed_empty|completed_with_objects)$",
    ),
    queue_scope: str = Query(
        default="current_filter",
        pattern="^(all_pending|current_filter|current_split)$",
    ),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_session),
) -> SampleNavigationResponse:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return sample_service.get_sample_navigation(
        session,
        dataset_id,
        sample_id=sample_id,
        search=search,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        annotation_progress=annotation_progress,
        queue_scope=queue_scope,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.patch("/datasets/{dataset_id}/samples/batch", response_model=BatchSampleUpdateResult)
def batch_update_dataset_samples(
    dataset_id: int,
    payload: BatchSampleUpdate,
    session: Session = Depends(get_session),
) -> BatchSampleUpdateResult:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return sample_service.batch_update_samples(session, dataset_id, payload)


@router.post("/datasets/{dataset_id}/split-plan", response_model=SplitPlanResult)
def apply_dataset_split_plan(
    dataset_id: int,
    payload: SplitPlanRequest,
    session: Session = Depends(get_session),
) -> SplitPlanResult:
    return split_service.apply_split_plan(session, dataset_id, payload)


@router.post("/datasets/{dataset_id}/samples/delete", response_model=SampleDeleteResult)
def delete_dataset_samples(
    dataset_id: int,
    payload: BatchSampleDelete,
    session: Session = Depends(get_session),
) -> SampleDeleteResult:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return sample_service.delete_samples(session, dataset_id, payload.sample_ids)


@router.post("/datasets/{dataset_id}/repair-missing", response_model=MissingSampleRepairResult)
def repair_dataset_missing_samples(
    dataset_id: int,
    payload: MissingSampleRepairRequest,
    session: Session = Depends(get_session),
) -> MissingSampleRepairResult:
    return sample_service.repair_missing_samples(session, dataset_id, payload)


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


@router.get("/datasets/{dataset_id}/quality-report", response_model=DatasetQualityReport)
def dataset_quality_report(
    dataset_id: int,
    issue_limit: int = Query(default=500, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> DatasetQualityReport:
    return quality_service.build_quality_report(session, dataset_id, issue_limit=issue_limit)


@router.get("/datasets/{dataset_id}/training-readiness", response_model=TrainingReadinessReport)
def dataset_training_readiness(
    dataset_id: int,
    session: Session = Depends(get_session),
) -> TrainingReadinessReport:
    return training_readiness_service.build_training_readiness_report(session, dataset_id)


@router.put(
    "/datasets/{dataset_id}/training-readiness/config",
    response_model=TrainingReadinessConfig,
)
def save_dataset_training_readiness_config(
    dataset_id: int,
    payload: TrainingReadinessConfigRequest,
    session: Session = Depends(get_session),
) -> TrainingReadinessConfig:
    try:
        return training_readiness_service.save_training_readiness_config(
            session,
            dataset_id,
            payload,
        )
    except training_readiness_service.TrainingReadinessConfigError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/datasets/{dataset_id}/training-readiness/exports",
    response_model=TrainingReadinessConfig,
)
def record_dataset_training_export(
    dataset_id: int,
    payload: TrainingReadinessConfigRequest,
    session: Session = Depends(get_session),
) -> TrainingReadinessConfig:
    try:
        return training_readiness_service.record_training_export(
            session,
            dataset_id,
            payload,
        )
    except training_readiness_service.TrainingReadinessConfigError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/export-manifest")
def export_dataset_manifest(
    dataset_id: int,
    search: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    file_status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    split: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
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
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
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
