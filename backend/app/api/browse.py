from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.browse import DatasetBrowseResponse
from app.services.dataset_browse_service import browse_dataset

router = APIRouter(prefix="/api", tags=["browse"])


@router.get("/datasets/{dataset_id}/browse", response_model=DatasetBrowseResponse)
def get_dataset_browse(
    dataset_id: int,
    folder: str = Query(default="", max_length=2000),
    source_root: str = Query(default="", max_length=2000),
    recursive: bool = False,
    search: str = Query(default="", max_length=2000),
    file_type: str = Query(default="", max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=60, ge=1, le=200),
    folder_page: int = Query(default=1, ge=1),
    folder_page_size: int = Query(default=100, ge=1, le=200),
    category_id: int | None = Query(default=None, ge=1),
    batch_id: int | None = Query(default=None, ge=1),
    all_sources: bool = False,
    session: Session = Depends(get_session),
) -> DatasetBrowseResponse:
    return browse_dataset(
        session, dataset_id, folder=folder, source_root=source_root, recursive=recursive,
        search=search, file_type=file_type, page=page, page_size=page_size,
        folder_page=folder_page, folder_page_size=folder_page_size,
        category_id=category_id, batch_id=batch_id, all_sources=all_sources,
    )
