from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.sample import SampleDeleteResult, SamplePreview, SampleRead, SampleRepairRequest, SampleUpdate
from app.schemas.tag import TagRead, TagUpdate
from app.services import sample_service, tag_service

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


@router.delete("/samples/{sample_id}", response_model=SampleDeleteResult)
def delete_sample(sample_id: int, session: Session = Depends(get_session)) -> SampleDeleteResult:
    return sample_service.delete_sample(session, sample_id)


@router.patch("/samples/{sample_id}/repair", response_model=SampleRead)
def repair_sample_file(
    sample_id: int,
    payload: SampleRepairRequest,
    session: Session = Depends(get_session),
) -> SampleRead:
    return sample_service.repair_sample_file(session, sample_id, payload)


@router.patch("/tags/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    session: Session = Depends(get_session),
) -> TagRead:
    return tag_service.update_tag(session, tag_id, payload)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: int, session: Session = Depends(get_session)) -> Response:
    tag_service.delete_tag(session, tag_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/samples/{sample_id}/preview", response_model=SamplePreview)
def get_sample_preview(sample_id: int, session: Session = Depends(get_session)) -> SamplePreview:
    sample = sample_service.get_sample_or_404(session, sample_id)
    return sample_service.get_sample_preview(sample)


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
