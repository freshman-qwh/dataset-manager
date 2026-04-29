from datetime import timezone

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.sample import Sample
from app.models.tag import Tag
from app.schemas.sample import SampleRead, SampleUpdate
from app.schemas.tag import TagRead
from app.models.dataset import utc_now


def to_sample_read(sample: Sample) -> SampleRead:
    tags = [TagRead.model_validate(tag) for tag in sorted(sample.tags, key=lambda item: item.name)]
    return SampleRead.model_validate(sample).model_copy(update={"tags": tags})


def list_samples(
    session: Session,
    dataset_id: int,
    search: str | None = None,
    file_type: str | None = None,
    tag: str | None = None,
) -> list[SampleRead]:
    statement = select(Sample).where(Sample.dataset_id == dataset_id)
    if file_type:
        statement = statement.where(Sample.file_type == file_type)

    samples = session.exec(statement.order_by(Sample.created_at.desc())).all()

    if search:
        needle = search.casefold()
        samples = [
            sample
            for sample in samples
            if needle in sample.filename.casefold()
            or needle in sample.relative_path.casefold()
            or needle in sample.file_hash.casefold()
        ]

    if tag:
        tag_needle = tag.casefold()
        samples = [
            sample
            for sample in samples
            if any(existing.name.casefold() == tag_needle for existing in sample.tags)
        ]

    return [to_sample_read(sample) for sample in samples]


def get_sample_or_404(session: Session, sample_id: int) -> Sample:
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample {sample_id} was not found.",
        )
    return sample


def get_sample(session: Session, sample_id: int) -> SampleRead:
    return to_sample_read(get_sample_or_404(session, sample_id))


def _get_or_create_tag(session: Session, dataset_id: int, name: str) -> Tag:
    clean_name = name.strip()
    existing = session.exec(
        select(Tag).where(Tag.dataset_id == dataset_id, Tag.name == clean_name)
    ).first()
    if existing:
        return existing

    tag = Tag(dataset_id=dataset_id, name=clean_name)
    session.add(tag)
    session.flush()
    return tag


def update_sample(session: Session, sample_id: int, payload: SampleUpdate) -> SampleRead:
    sample = get_sample_or_404(session, sample_id)
    updates = payload.model_dump(exclude_unset=True)

    if "split" in updates:
        sample.split = updates["split"]
    if "notes" in updates:
        sample.notes = updates["notes"]
    if "tags" in updates and updates["tags"] is not None:
        unique_names = []
        seen = set()
        for raw_name in updates["tags"]:
            name = raw_name.strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                unique_names.append(name)
        sample.tags = [_get_or_create_tag(session, sample.dataset_id, name) for name in unique_names]

    sample.updated_at = utc_now().astimezone(timezone.utc)
    session.add(sample)
    session.commit()
    session.refresh(sample)
    return to_sample_read(sample)
