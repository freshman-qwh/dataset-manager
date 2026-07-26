from sqlalchemy import distinct, exists, func
from sqlmodel import Session, select

from app.models.annotation import Annotation
from app.models.sample import Sample, SampleTagLink
from app.models.tag import Tag
from app.schemas.stats import DatasetStats
from app.services.dataset_service import get_dataset_or_404


def get_dataset_stats(session: Session, dataset_id: int) -> DatasetStats:
    get_dataset_or_404(session, dataset_id)
    sample_count, total_size = session.exec(
        select(
            func.count(Sample.id),
            func.coalesce(func.sum(Sample.file_size), 0),
        ).where(Sample.dataset_id == dataset_id)
    ).one()
    by_file_type = _group_counts(session, dataset_id, Sample.file_type)
    by_extension = _group_counts(session, dataset_id, Sample.extension)
    by_status = _group_counts(session, dataset_id, Sample.file_status)
    by_split = _group_counts(
        session,
        dataset_id,
        func.coalesce(Sample.split, "unassigned"),
    )
    by_annotation_progress = _group_counts(
        session,
        dataset_id,
        func.coalesce(Sample.annotation_progress, "not_started"),
    )
    by_review_status = _group_counts(
        session,
        dataset_id,
        func.coalesce(Sample.review_status, "not_reviewed"),
    )
    duplicate_counts = [
        int(count)
        for count in session.exec(
            select(func.count(Sample.id))
            .where(
                Sample.dataset_id == dataset_id,
                Sample.file_hash != "",
            )
            .group_by(Sample.file_hash)
            .having(func.count(Sample.id) > 1)
        ).all()
    ]
    tag_counts = {
        name: int(count)
        for name, count in session.exec(
            select(Tag.name, func.count(SampleTagLink.sample_id))
            .join(SampleTagLink, SampleTagLink.tag_id == Tag.id)
            .where(Tag.dataset_id == dataset_id)
            .group_by(Tag.id, Tag.name)
        ).all()
    }
    untagged_samples = session.exec(
        select(func.count(Sample.id)).where(
            Sample.dataset_id == dataset_id,
            ~exists(
                select(SampleTagLink.sample_id).where(
                    SampleTagLink.sample_id == Sample.id
                )
            ),
        )
    ).one()
    annotation_count, samples_with_objects = session.exec(
        select(
            func.count(Annotation.id),
            func.count(distinct(Annotation.sample_id)),
        ).where(Annotation.dataset_id == dataset_id)
    ).one()
    annotation_label_rows = session.exec(
        select(Annotation.label, func.count(Annotation.id))
        .where(Annotation.dataset_id == dataset_id)
        .group_by(Annotation.label)
    ).all()
    by_annotation_label = {label: int(count) for label, count in annotation_label_rows}

    return DatasetStats(
        dataset_id=dataset_id,
        sample_count=int(sample_count),
        total_size=int(total_size),
        by_file_type=by_file_type,
        by_extension=by_extension,
        by_status=by_status,
        by_split=by_split,
        by_annotation_progress=by_annotation_progress,
        by_review_status=by_review_status,
        tag_counts=tag_counts,
        duplicate_groups=len(duplicate_counts),
        duplicate_samples=sum(duplicate_counts),
        untagged_samples=untagged_samples,
        samples_with_objects=int(samples_with_objects),
        annotation_count=int(annotation_count),
        by_annotation_label=by_annotation_label,
    )


def _group_counts(session: Session, dataset_id: int, group_expression) -> dict[str, int]:
    rows = session.exec(
        select(group_expression, func.count(Sample.id))
        .where(Sample.dataset_id == dataset_id)
        .group_by(group_expression)
    ).all()
    return {
        str(value): int(count)
        for value, count in rows
        if value is not None
    }
