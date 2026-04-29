from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.dataset import DatasetCreate, DatasetRead, DatasetUpdate
from app.schemas.sample import SampleRead
from app.schemas.scan import ScanRequest, ScanResult
from app.schemas.stats import DatasetStats
from app.services import dataset_service, manifest_service, sample_service, scan_service, stats_service

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


@router.get("/datasets/{dataset_id}/samples", response_model=list[SampleRead])
def list_dataset_samples(
    dataset_id: int,
    search: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[SampleRead]:
    dataset_service.get_dataset_or_404(session, dataset_id)
    return sample_service.list_samples(session, dataset_id, search, file_type, tag)


@router.get("/stats/datasets/{dataset_id}", response_model=DatasetStats)
def dataset_stats(dataset_id: int, session: Session = Depends(get_session)) -> DatasetStats:
    return stats_service.get_dataset_stats(session, dataset_id)


@router.get("/datasets/{dataset_id}/export-manifest")
def export_dataset_manifest(dataset_id: int, session: Session = Depends(get_session)) -> dict:
    return manifest_service.export_manifest(session, dataset_id)
