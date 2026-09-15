from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.core.database import get_session
from app.core.job_runtime import job_runner
from app.schemas.dataset import DatasetCreate, DatasetRead, DatasetUpdate
from app.schemas.dataset_saved_view import DatasetSavedViewCreate, DatasetSavedViewRead
from app.schemas.dataset_snapshot import (
    DatasetSnapshotChangeType,
    DatasetSnapshotCreate,
    DatasetSnapshotDiffResponse,
    DatasetSnapshotDocument,
    DatasetSnapshotRead,
    DatasetSnapshotTrainingLabels,
)
from app.schemas.duplicates import DuplicateReport
from app.schemas.export_template import ExportTemplateResponse
from app.schemas.metadata_import import (
    MetadataImportJobCreateRequest,
    MetadataImportJobCreateResponse,
    MetadataImportRequest,
    MetadataImportResult,
)
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
from app.schemas.scan import ScanJobCreateResponse, ScanRequest, ScanResult
from app.schemas.split import SplitPlanRequest, SplitPlanResult
from app.schemas.stats import DatasetStats
from app.schemas.tag import TagCreate, TagRead
from app.schemas.thumbnail import ThumbnailJobCreateResponse, ThumbnailJobRequest
from app.schemas.training_readiness import (
    TrainingReadinessConfig,
    TrainingReadinessConfigRequest,
    TrainingReadinessReport,
)
from app.services import (
    dataset_service,
    dataset_saved_view_service,
    dataset_snapshot_service,
    dataset_snapshot_compare_service,
    duplicate_service,
    export_template_service,
    job_service,
    manifest_service,
    metadata_import_service,
    metadata_import_job_service,
    quality_service,
    sample_service,
    scan_job_service,
    scan_service,
    split_service,
    stats_service,
    tag_service,
    thumbnail_job_service,
    training_readiness_service,
)

router = APIRouter(prefix="/api", tags=["datasets"])


def _raise_snapshot_http_error(exc: dataset_snapshot_service.DatasetSnapshotError) -> NoReturn:
    if isinstance(exc, dataset_snapshot_service.DatasetSnapshotSchemaUnavailableError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if isinstance(exc, dataset_snapshot_service.DatasetSnapshotStaleError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, dataset_snapshot_service.DatasetSnapshotArtifactError):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _raise_saved_view_http_error(exc: dataset_saved_view_service.DatasetSavedViewError) -> NoReturn:
    if isinstance(exc, dataset_saved_view_service.DatasetSavedViewSchemaUnavailableError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if isinstance(exc, dataset_saved_view_service.DatasetSavedViewConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, dataset_saved_view_service.DatasetSavedViewDataError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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


@router.post(
    "/datasets/{dataset_id}/saved-views",
    response_model=DatasetSavedViewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_saved_view(
    dataset_id: int,
    payload: DatasetSavedViewCreate,
    session: Session = Depends(get_session),
) -> DatasetSavedViewRead:
    try:
        return dataset_saved_view_service.create_saved_view(session, dataset_id, payload)
    except dataset_saved_view_service.DatasetSavedViewError as exc:
        _raise_saved_view_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/saved-views",
    response_model=list[DatasetSavedViewRead],
)
def list_dataset_saved_views(
    dataset_id: int,
    session: Session = Depends(get_session),
) -> list[DatasetSavedViewRead]:
    try:
        return dataset_saved_view_service.list_saved_views(session, dataset_id)
    except dataset_saved_view_service.DatasetSavedViewError as exc:
        _raise_saved_view_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/saved-views/{saved_view_id}",
    response_model=DatasetSavedViewRead,
)
def get_dataset_saved_view(
    dataset_id: int,
    saved_view_id: int,
    session: Session = Depends(get_session),
) -> DatasetSavedViewRead:
    try:
        return dataset_saved_view_service.get_saved_view(session, dataset_id, saved_view_id)
    except dataset_saved_view_service.DatasetSavedViewError as exc:
        _raise_saved_view_http_error(exc)


@router.delete(
    "/datasets/{dataset_id}/saved-views/{saved_view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_dataset_saved_view(
    dataset_id: int,
    saved_view_id: int,
    session: Session = Depends(get_session),
) -> Response:
    try:
        dataset_saved_view_service.delete_saved_view(session, dataset_id, saved_view_id)
    except dataset_saved_view_service.DatasetSavedViewError as exc:
        _raise_saved_view_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/datasets/{dataset_id}/scan", response_model=ScanResult)
def scan_dataset(
    dataset_id: int,
    payload: ScanRequest,
    session: Session = Depends(get_session),
) -> ScanResult:
    return scan_service.scan_dataset(session, dataset_id, payload)


@router.post(
    "/datasets/{dataset_id}/scan-jobs",
    response_model=ScanJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_scan_job(
    dataset_id: int,
    payload: ScanRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> ScanJobCreateResponse:
    try:
        result = scan_job_service.create_scan_job(session, dataset_id, payload)
    except job_service.JobSchemaUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result


@router.post(
    "/datasets/{dataset_id}/thumbnail-jobs",
    response_model=ThumbnailJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_thumbnail_job(
    dataset_id: int,
    payload: ThumbnailJobRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> ThumbnailJobCreateResponse:
    try:
        result = thumbnail_job_service.create_thumbnail_job(
            session,
            dataset_id,
            payload,
        )
    except job_service.JobSchemaUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    if result.job is not None:
        job_runner.notify()
    return result


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
    triage_status: str | None = Query(
        default=None,
        pattern="^(untriaged|pending|ok|ng)$",
    ),
    ok_grade: str | None = Query(default=None, pattern="^(clear|borderline)$"),
    defect_severity: str | None = Query(
        default=None,
        pattern="^(mild|moderate|severe)$",
    ),
    defect_type_id: int | None = Query(default=None, gt=0),
    triage_outdated: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=60, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    thumbnail_prefetch: int = Query(default=0, ge=0, le=12),
    session: Session = Depends(get_session),
) -> SampleListResponse:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return sample_service.list_samples(
        session,
        dataset_id,
        search=search,
        file_type=file_type,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        annotation_progress=annotation_progress,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        thumbnail_prefetch=thumbnail_prefetch,
        triage_status=triage_status,
        ok_grade=ok_grade,
        defect_severity=defect_severity,
        defect_type_id=defect_type_id,
        triage_outdated=triage_outdated,
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
def dataset_duplicates(
    dataset_id: int,
    leakage_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> Response:
    report = duplicate_service.get_duplicate_report(
        session,
        dataset_id,
        leakage_only=leakage_only,
        page=page,
        page_size=page_size,
    )
    return Response(
        content=report.model_dump_json(),
        media_type="application/json",
    )


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


@router.post(
    "/datasets/{dataset_id}/metadata-import-jobs",
    response_model=MetadataImportJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_metadata_import_job(
    dataset_id: int,
    payload: MetadataImportJobCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> MetadataImportJobCreateResponse:
    try:
        result = metadata_import_job_service.create_metadata_import_job(
            session,
            dataset_id,
            payload,
        )
    except job_service.JobSchemaUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except job_service.JobError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    job_runner.notify()
    return result


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


@router.post(
    "/datasets/{dataset_id}/snapshots",
    response_model=DatasetSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_snapshot(
    dataset_id: int,
    payload: DatasetSnapshotCreate,
    session: Session = Depends(get_session),
) -> DatasetSnapshotRead:
    try:
        return dataset_snapshot_service.create_snapshot(session, dataset_id, payload)
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/snapshots",
    response_model=list[DatasetSnapshotRead],
)
def list_dataset_snapshots(
    dataset_id: int,
    session: Session = Depends(get_session),
) -> list[DatasetSnapshotRead]:
    try:
        return dataset_snapshot_service.list_snapshots(session, dataset_id)
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/snapshots/compare",
    response_model=DatasetSnapshotDiffResponse,
)
def compare_dataset_snapshots(
    dataset_id: int,
    base_snapshot_id: int = Query(gt=0),
    target_snapshot_id: int = Query(gt=0),
    change_type: DatasetSnapshotChangeType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> DatasetSnapshotDiffResponse:
    try:
        return dataset_snapshot_compare_service.compare_snapshots(
            session,
            dataset_id,
            base_snapshot_id,
            target_snapshot_id,
            change_type=change_type,
            page=page,
            page_size=page_size,
        )
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/snapshots/{snapshot_id}",
    response_model=DatasetSnapshotRead,
)
def get_dataset_snapshot(
    dataset_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> DatasetSnapshotRead:
    try:
        return dataset_snapshot_service.get_snapshot_read(session, dataset_id, snapshot_id)
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/snapshots/{snapshot_id}/content",
    response_model=DatasetSnapshotDocument,
)
def read_dataset_snapshot(
    dataset_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> DatasetSnapshotDocument:
    try:
        return dataset_snapshot_service.read_snapshot_document(session, dataset_id, snapshot_id)
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/snapshots/{snapshot_id}/training-labels",
    response_model=DatasetSnapshotTrainingLabels,
)
def rebuild_dataset_snapshot_training_labels(
    dataset_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> DatasetSnapshotTrainingLabels:
    try:
        return dataset_snapshot_compare_service.rebuild_training_labels(
            session, dataset_id, snapshot_id
        )
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)


@router.get(
    "/datasets/{dataset_id}/snapshots/{snapshot_id}/training-labels/download"
)
def download_dataset_snapshot_training_labels(
    dataset_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> Response:
    try:
        result = dataset_snapshot_compare_service.rebuild_training_labels(
            session, dataset_id, snapshot_id
        )
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)
    content = result.model_dump_json(indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="dataset-{dataset_id}-snapshot-{snapshot_id}-training-labels.json"'
            )
        },
    )


@router.get("/datasets/{dataset_id}/snapshots/{snapshot_id}/download")
def download_dataset_snapshot(
    dataset_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> FileResponse:
    try:
        snapshot = dataset_snapshot_service.get_snapshot_read(session, dataset_id, snapshot_id)
        path = dataset_snapshot_service.snapshot_artifact_path(session, dataset_id, snapshot_id)
    except dataset_snapshot_service.DatasetSnapshotError as exc:
        _raise_snapshot_http_error(exc)
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"dataset-{dataset_id}-revision-{snapshot.dataset_revision}-snapshot-{snapshot_id}.json",
    )


@router.get("/datasets/{dataset_id}/export-template", response_model=ExportTemplateResponse)
def export_dataset_template(
    dataset_id: int,
    format: str = Query(default="csv"),
    session: Session = Depends(get_session),
) -> ExportTemplateResponse:
    return export_template_service.export_template(session, dataset_id, format)
