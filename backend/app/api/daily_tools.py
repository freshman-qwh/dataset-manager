from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.daily_tools import (
    CoverageRead, CoverageSamplesRead, CoverageStatus, FilenameLookupRead,
    FilenameLookupRequest, FilenameLookupResult,
)
from app.services.daily_tools_service import lookup_candidates, lookup_filenames, read_coverage, read_coverage_samples

router = APIRouter(prefix="/api", tags=["daily-tools"])


@router.post("/datasets/{dataset_id}/filename-lookup", response_model=FilenameLookupRead)
def find_filenames(dataset_id: int, payload: FilenameLookupRequest,
                   session: Session = Depends(get_session)) -> FilenameLookupRead:
    return lookup_filenames(session, dataset_id, payload.entries)


@router.get("/datasets/{dataset_id}/filename-lookup/candidates", response_model=FilenameLookupResult)
def find_candidates(dataset_id: int, entry: str = Query(min_length=1, max_length=2000),
                    page: int = Query(1, ge=1), page_size: int = Query(5, ge=1, le=20),
                    session: Session = Depends(get_session)) -> FilenameLookupResult:
    return lookup_candidates(session, dataset_id, entry, page=page, page_size=page_size)


@router.get("/datasets/{dataset_id}/coverage", response_model=CoverageRead)
def get_coverage(dataset_id: int, session: Session = Depends(get_session)) -> CoverageRead:
    return read_coverage(session, dataset_id)


@router.get("/datasets/{dataset_id}/coverage/samples", response_model=CoverageSamplesRead)
def get_coverage_samples(dataset_id: int, category_id: int | None = Query(None, ge=1),
                         batch_id: int | None = Query(None, ge=1), status: CoverageStatus = "all",
                         page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=24),
                         session: Session = Depends(get_session)) -> CoverageSamplesRead:
    # An omitted axis means unassigned, deliberately not every category/batch.
    return read_coverage_samples(session, dataset_id, category_id=category_id, batch_id=batch_id,
        status=status, page=page, page_size=page_size)
