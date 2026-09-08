import json

from sqlalchemy import func, inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.dataset_saved_view import DatasetSavedView
from app.schemas.dataset_saved_view import DatasetSavedViewCreate, DatasetSavedViewQuery, DatasetSavedViewRead
from app.services.dataset_service import get_dataset_or_404


class DatasetSavedViewError(RuntimeError):
    pass


class DatasetSavedViewSchemaUnavailableError(DatasetSavedViewError):
    pass


class DatasetSavedViewNotFoundError(DatasetSavedViewError):
    pass


class DatasetSavedViewConflictError(DatasetSavedViewError):
    pass


class DatasetSavedViewDataError(DatasetSavedViewError):
    pass


def _ensure_schema(session: Session) -> None:
    bind = session.get_bind()
    if "dataset_saved_views" not in inspect(bind).get_table_names():
        raise DatasetSavedViewSchemaUnavailableError(
            "Saved views require the latest database migration."
        )


def _to_read(saved_view: DatasetSavedView) -> DatasetSavedViewRead:
    try:
        sample_query = DatasetSavedViewQuery.model_validate_json(saved_view.query_json)
    except (ValueError, json.JSONDecodeError) as exc:
        raise DatasetSavedViewDataError(
            f"Saved view {saved_view.id} contains invalid query data."
        ) from exc
    return DatasetSavedViewRead(
        id=saved_view.id or 0,
        dataset_id=saved_view.dataset_id,
        name=saved_view.name,
        task_type=saved_view.task_type,
        queue_scope=saved_view.queue_scope,
        sample_query=sample_query,
        created_at=saved_view.created_at,
        updated_at=saved_view.updated_at,
    )


def list_saved_views(session: Session, dataset_id: int) -> list[DatasetSavedViewRead]:
    _ensure_schema(session)
    get_dataset_or_404(session, dataset_id)
    rows = session.exec(
        select(DatasetSavedView)
        .where(DatasetSavedView.dataset_id == dataset_id)
        .order_by(DatasetSavedView.updated_at.desc(), DatasetSavedView.id.desc())
    ).all()
    return [_to_read(row) for row in rows]


def get_saved_view(
    session: Session,
    dataset_id: int,
    saved_view_id: int,
) -> DatasetSavedViewRead:
    _ensure_schema(session)
    get_dataset_or_404(session, dataset_id)
    row = session.exec(
        select(DatasetSavedView).where(
            DatasetSavedView.id == saved_view_id,
            DatasetSavedView.dataset_id == dataset_id,
        )
    ).first()
    if row is None:
        raise DatasetSavedViewNotFoundError(
            f"Saved view {saved_view_id} was not found for dataset {dataset_id}."
        )
    return _to_read(row)


def create_saved_view(
    session: Session,
    dataset_id: int,
    payload: DatasetSavedViewCreate,
) -> DatasetSavedViewRead:
    _ensure_schema(session)
    dataset = get_dataset_or_404(session, dataset_id)
    duplicate = session.exec(
        select(DatasetSavedView.id).where(
            DatasetSavedView.dataset_id == dataset_id,
            func.lower(DatasetSavedView.name) == payload.name.casefold(),
        )
    ).first()
    if duplicate is not None:
        raise DatasetSavedViewConflictError(
            f'A saved view named "{payload.name}" already exists.'
        )

    now = utc_now()
    row = DatasetSavedView(
        dataset_id=dataset_id,
        name=payload.name,
        task_type=dataset.task_type,
        queue_scope=payload.queue_scope,
        query_json=payload.sample_query.model_dump_json(),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DatasetSavedViewConflictError(
            f'A saved view named "{payload.name}" already exists.'
        ) from exc
    session.refresh(row)
    return _to_read(row)


def delete_saved_view(session: Session, dataset_id: int, saved_view_id: int) -> None:
    _ensure_schema(session)
    get_dataset_or_404(session, dataset_id)
    row = session.exec(
        select(DatasetSavedView).where(
            DatasetSavedView.id == saved_view_id,
            DatasetSavedView.dataset_id == dataset_id,
        )
    ).first()
    if row is None:
        raise DatasetSavedViewNotFoundError(
            f"Saved view {saved_view_id} was not found for dataset {dataset_id}."
        )
    session.delete(row)
    session.commit()


def delete_dataset_saved_views(session: Session, dataset_id: int) -> None:
    if "dataset_saved_views" not in inspect(session.get_bind()).get_table_names():
        return
    rows = session.exec(
        select(DatasetSavedView).where(DatasetSavedView.dataset_id == dataset_id)
    ).all()
    for row in rows:
        session.delete(row)
