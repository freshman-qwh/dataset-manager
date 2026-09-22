from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.workflow import DEFECT_SEVERITY_VALUES, OK_GRADE_VALUES, TRIAGE_STATUS_VALUES
from app.schemas.triage import (
    BatchTriageCommitRequest,
    BatchTriageCommitResponse,
    BatchTriagePreviewRequest,
    BatchTriagePreviewResponse,
    DefectTypeCreate,
    DefectTypeRead,
    DefectTypeUpdate,
    SampleTriageRead,
    SampleTriageWrite,
    TriageNavigationResponse,
    TriagePolicyImpactPreview,
    TriagePolicyPreviewRequest,
    TriagePolicyRead,
    TriagePolicyUpdateRequest,
    TriageQueueScope,
    TriageStats,
)
from app.services import triage_service


router = APIRouter(prefix="/api", tags=["triage"])


def _raise_triage_error(exc: triage_service.TriageError) -> None:
    if isinstance(exc, triage_service.TriageSchemaUnavailableError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, triage_service.TriageConflictError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, triage_service.TriageNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/triage-policy", response_model=TriagePolicyRead)
def get_triage_policy(
    dataset_id: int,
    session: Session = Depends(get_session),
) -> TriagePolicyRead:
    try:
        return triage_service.get_triage_policy(session, dataset_id)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.put("/datasets/{dataset_id}/triage-policy", response_model=TriagePolicyRead)
def update_triage_policy(
    dataset_id: int,
    payload: TriagePolicyUpdateRequest,
    session: Session = Depends(get_session),
) -> TriagePolicyRead:
    try:
        return triage_service.update_triage_policy(session, dataset_id, payload)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.post(
    "/datasets/{dataset_id}/triage-policy/preview",
    response_model=TriagePolicyImpactPreview,
)
def preview_triage_policy(
    dataset_id: int,
    payload: TriagePolicyPreviewRequest,
    session: Session = Depends(get_session),
) -> TriagePolicyImpactPreview:
    try:
        return triage_service.preview_triage_policy_change(session, dataset_id, payload)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.get("/datasets/{dataset_id}/defect-types", response_model=list[DefectTypeRead])
def list_defect_types(
    dataset_id: int,
    include_inactive: bool = Query(default=True),
    session: Session = Depends(get_session),
) -> list[DefectTypeRead]:
    try:
        return triage_service.list_defect_types(
            session,
            dataset_id,
            include_inactive=include_inactive,
        )
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.post(
    "/datasets/{dataset_id}/defect-types",
    response_model=DefectTypeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_defect_type(
    dataset_id: int,
    payload: DefectTypeCreate,
    session: Session = Depends(get_session),
) -> DefectTypeRead:
    try:
        return triage_service.create_defect_type(session, dataset_id, payload)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.patch(
    "/datasets/{dataset_id}/defect-types/{defect_type_id}",
    response_model=DefectTypeRead,
)
def update_defect_type(
    dataset_id: int,
    defect_type_id: int,
    payload: DefectTypeUpdate,
    session: Session = Depends(get_session),
) -> DefectTypeRead:
    try:
        return triage_service.update_defect_type(
            session,
            dataset_id,
            defect_type_id,
            payload,
        )
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.get("/samples/{sample_id}/triage", response_model=SampleTriageRead)
def get_sample_triage(
    sample_id: int,
    session: Session = Depends(get_session),
) -> SampleTriageRead:
    try:
        return triage_service.get_sample_triage(session, sample_id)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.put("/samples/{sample_id}/triage", response_model=SampleTriageRead)
def replace_sample_triage(
    sample_id: int,
    payload: SampleTriageWrite,
    session: Session = Depends(get_session),
) -> SampleTriageRead:
    try:
        return triage_service.replace_sample_triage(session, sample_id, payload)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.post(
    "/datasets/{dataset_id}/triage/batch-preview",
    response_model=BatchTriagePreviewResponse,
)
def preview_batch_triage(
    dataset_id: int,
    payload: BatchTriagePreviewRequest,
    session: Session = Depends(get_session),
) -> BatchTriagePreviewResponse:
    try:
        return triage_service.preview_batch_triage(session, dataset_id, payload)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.post(
    "/datasets/{dataset_id}/triage/batch",
    response_model=BatchTriageCommitResponse,
)
def commit_batch_triage(
    dataset_id: int,
    payload: BatchTriageCommitRequest,
    session: Session = Depends(get_session),
) -> BatchTriageCommitResponse:
    try:
        return triage_service.commit_batch_triage(session, dataset_id, payload)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.get(
    "/datasets/{dataset_id}/triage/navigation",
    response_model=TriageNavigationResponse,
)
def get_triage_navigation(
    dataset_id: int,
    sample_id: int | None = Query(default=None, gt=0),
    target_index: int | None = Query(default=None, ge=1),
    queue_scope: TriageQueueScope = Query(default="untriaged"),
    search: str | None = Query(default=None, max_length=300),
    split: str | None = Query(default=None, max_length=40),
    triage_status: str | None = Query(default=None, pattern=f"^({'|'.join(TRIAGE_STATUS_VALUES)})$"),
    ok_grade: str | None = Query(default=None, pattern=f"^({'|'.join(OK_GRADE_VALUES)})$"),
    defect_severity: str | None = Query(
        default=None,
        pattern=f"^({'|'.join(DEFECT_SEVERITY_VALUES)})$",
    ),
    defect_type_id: int | None = Query(default=None, gt=0),
    session: Session = Depends(get_session),
) -> TriageNavigationResponse:
    try:
        return triage_service.get_triage_navigation(
            session,
            dataset_id,
            sample_id=sample_id,
            target_index=target_index,
            queue_scope=queue_scope,
            search=search,
            split=split,
            triage_status=triage_status,
            ok_grade=ok_grade,
            defect_severity=defect_severity,
            defect_type_id=defect_type_id,
        )
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)


@router.get("/datasets/{dataset_id}/triage/stats", response_model=TriageStats)
def get_triage_stats(
    dataset_id: int,
    session: Session = Depends(get_session),
) -> TriageStats:
    try:
        return triage_service.get_triage_stats(session, dataset_id)
    except triage_service.TriageError as exc:
        _raise_triage_error(exc)
