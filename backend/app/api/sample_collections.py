from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.sample_collection import CollectionKind, SampleCollectionCreate, SampleCollectionRead, SampleCollectionUpdate
from app.services import sample_collection_service as service

router = APIRouter(prefix="/api/sample-collections", tags=["sample-collections"])


@router.get("", response_model=list[SampleCollectionRead])
def list_collections(kind: CollectionKind | None = None, dataset_id: int | None = Query(None, gt=0), category_id: int | None = Query(None, gt=0), session: Session = Depends(get_session)):
    return service.list_collections(session, kind, dataset_id, category_id)


@router.post("", response_model=SampleCollectionRead, status_code=201)
def create_collection(payload: SampleCollectionCreate, session: Session = Depends(get_session)):
    return service.create_collection(session, payload)


@router.get("/{collection_id}", response_model=SampleCollectionRead)
def get_collection(collection_id: int, session: Session = Depends(get_session)):
    return service.get_collection(session, collection_id)


@router.patch("/{collection_id}", response_model=SampleCollectionRead)
def update_collection(collection_id: int, payload: SampleCollectionUpdate, session: Session = Depends(get_session)):
    return service.update_collection(session, collection_id, payload)


@router.delete("/{collection_id}", status_code=204)
def delete_collection(collection_id: int, expected_version: int = Query(..., ge=1), session: Session = Depends(get_session)):
    service.delete_collection(session, collection_id, expected_version)
    return Response(status_code=204)
