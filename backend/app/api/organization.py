from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.organization import (
    BatchCreate, BatchRead, BatchUpdate, CategoryCreate, CategoryRead, CategoryUpdate,
    DatasetOrganizationRead, OrganizationAssign, OrganizationAssignRead,
    ProjectCreate, ProjectRead, ProjectUpdate,
)
from app.services import organization_service as service

router = APIRouter(prefix="/api", tags=["organization"])


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)):
    return service.list_projects(session)


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)):
    return service.create_project(session, payload)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, session: Session = Depends(get_session)):
    return service.update_project(session, project_id, payload)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)):
    service.delete_project(session, project_id)
    return Response(status_code=204)


@router.get("/datasets/{dataset_id}/organization", response_model=DatasetOrganizationRead)
def read_organization(dataset_id: int, session: Session = Depends(get_session)):
    return service.read_organization(session, dataset_id)


@router.patch("/datasets/{dataset_id}/organization/assign", response_model=OrganizationAssignRead)
def assign_organization(dataset_id: int, payload: OrganizationAssign, session: Session = Depends(get_session)):
    return service.assign_samples(session, dataset_id, payload)


@router.get("/datasets/{dataset_id}/categories", response_model=list[CategoryRead])
def list_categories(dataset_id: int, session: Session = Depends(get_session)):
    return service.list_categories(session, dataset_id)


@router.post("/datasets/{dataset_id}/categories", response_model=CategoryRead, status_code=201)
def create_category(dataset_id: int, payload: CategoryCreate, session: Session = Depends(get_session)):
    return service.create_category(session, dataset_id, payload)


@router.patch("/datasets/{dataset_id}/categories/{category_id}", response_model=CategoryRead)
def update_category(dataset_id: int, category_id: int, payload: CategoryUpdate, session: Session = Depends(get_session)):
    return service.update_category(session, dataset_id, category_id, payload)


@router.delete("/datasets/{dataset_id}/categories/{category_id}", status_code=204)
def delete_category(dataset_id: int, category_id: int, session: Session = Depends(get_session)):
    service.delete_category(session, dataset_id, category_id)
    return Response(status_code=204)


@router.get("/datasets/{dataset_id}/batches", response_model=list[BatchRead])
def list_batches(dataset_id: int, session: Session = Depends(get_session)):
    return service.list_batches(session, dataset_id)


@router.post("/datasets/{dataset_id}/batches", response_model=BatchRead, status_code=201)
def create_batch(dataset_id: int, payload: BatchCreate, session: Session = Depends(get_session)):
    return service.create_batch(session, dataset_id, payload)


@router.patch("/datasets/{dataset_id}/batches/{batch_id}", response_model=BatchRead)
def update_batch(dataset_id: int, batch_id: int, payload: BatchUpdate, session: Session = Depends(get_session)):
    return service.update_batch(session, dataset_id, batch_id, payload)


@router.delete("/datasets/{dataset_id}/batches/{batch_id}", status_code=204)
def delete_batch(dataset_id: int, batch_id: int, session: Session = Depends(get_session)):
    service.delete_batch(session, dataset_id, batch_id)
    return Response(status_code=204)
