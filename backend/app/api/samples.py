from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.sample import SampleRead, SampleUpdate
from app.services import sample_service

router = APIRouter(prefix="/api", tags=["samples"])


@router.get("/samples/{sample_id}", response_model=SampleRead)
def get_sample(sample_id: int, session: Session = Depends(get_session)) -> SampleRead:
    return sample_service.get_sample(session, sample_id)


@router.patch("/samples/{sample_id}", response_model=SampleRead)
def update_sample(
    sample_id: int,
    payload: SampleUpdate,
    session: Session = Depends(get_session),
) -> SampleRead:
    return sample_service.update_sample(session, sample_id, payload)


@router.get("/samples/{sample_id}/file")
def read_sample_file(sample_id: int, session: Session = Depends(get_session)) -> FileResponse:
    sample = sample_service.get_sample_or_404(session, sample_id)
    path = Path(sample.absolute_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sample file is missing from disk.",
        )
    return FileResponse(path, media_type=sample.mime_type, filename=sample.filename)
