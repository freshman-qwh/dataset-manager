from datetime import timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.models.dataset import Dataset, utc_now
from app.models.sample import Sample
from app.models.tag import Tag
from app.schemas.dataset import DatasetCreate, DatasetRead, DatasetUpdate
from app.core.workflow import task_capabilities


def _dataset_read(session: Session, dataset: Dataset) -> DatasetRead:
    count = session.exec(
        select(func.count(Sample.id)).where(Sample.dataset_id == dataset.id)
    ).one()
    return DatasetRead.model_validate(
        {
            **dataset.__dict__,
            "sample_count": count,
            "task_capabilities": task_capabilities(dataset.task_type),
        }
    )


def list_datasets(session: Session) -> list[DatasetRead]:
    datasets = session.exec(select(Dataset).order_by(Dataset.created_at.desc())).all()
    return [_dataset_read(session, dataset) for dataset in datasets]


def create_dataset(session: Session, payload: DatasetCreate) -> DatasetRead:
    dataset = Dataset(**payload.model_dump())
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return _dataset_read(session, dataset)


def get_dataset_or_404(session: Session, dataset_id: int) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} was not found.",
        )
    return dataset


def get_dataset(session: Session, dataset_id: int) -> DatasetRead:
    return _dataset_read(session, get_dataset_or_404(session, dataset_id))


def update_dataset(session: Session, dataset_id: int, payload: DatasetUpdate) -> DatasetRead:
    dataset = get_dataset_or_404(session, dataset_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(dataset, key, value)
    dataset.updated_at = utc_now().astimezone(timezone.utc)
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return _dataset_read(session, dataset)


def delete_dataset(session: Session, dataset_id: int) -> None:
    from app.services import annotation_service

    dataset = get_dataset_or_404(session, dataset_id)
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
    annotation_service.delete_sample_annotations(session, [sample.id for sample in samples if sample.id is not None])
    for sample in samples:
        sample.tags.clear()
        session.add(sample)
        session.delete(sample)

    tags = session.exec(select(Tag).where(Tag.dataset_id == dataset_id)).all()
    for tag in tags:
        session.delete(tag)

    session.delete(dataset)
    session.commit()
