from sqlalchemy import distinct, func
from sqlmodel import Session, select

from app.models.annotation import Annotation
from app.models.sample import Sample
from app.schemas.stats import DatasetStats
from app.services.dataset_service import get_dataset_or_404


def get_dataset_stats(session: Session, dataset_id: int) -> DatasetStats:
    get_dataset_or_404(session, dataset_id)
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()

    by_file_type: dict[str, int] = {}
    by_extension: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_split: dict[str, int] = {}
    by_annotation_progress: dict[str, int] = {}
    by_review_status: dict[str, int] = {}
    hash_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    total_size = 0
    untagged_samples = 0

    for sample in samples:
        total_size += sample.file_size
        by_file_type[sample.file_type] = by_file_type.get(sample.file_type, 0) + 1
        by_extension[sample.extension] = by_extension.get(sample.extension, 0) + 1
        by_status[sample.file_status] = by_status.get(sample.file_status, 0) + 1
        split = sample.split or "unassigned"
        by_split[split] = by_split.get(split, 0) + 1
        annotation_progress = sample.annotation_progress or "not_started"
        by_annotation_progress[annotation_progress] = by_annotation_progress.get(annotation_progress, 0) + 1
        review_status = sample.review_status or "not_reviewed"
        by_review_status[review_status] = by_review_status.get(review_status, 0) + 1
        hash_counts[sample.file_hash] = hash_counts.get(sample.file_hash, 0) + 1
        if not sample.tags:
            untagged_samples += 1
        for tag in sample.tags:
            tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1

    duplicate_counts = [count for count in hash_counts.values() if count > 1]
    annotation_count = session.exec(
        select(func.count(Annotation.id)).where(Annotation.dataset_id == dataset_id)
    ).one()
    samples_with_objects = session.exec(
        select(func.count(distinct(Annotation.sample_id))).where(Annotation.dataset_id == dataset_id)
    ).one()
    annotation_label_rows = session.exec(
        select(Annotation.label, func.count(Annotation.id))
        .where(Annotation.dataset_id == dataset_id)
        .group_by(Annotation.label)
    ).all()
    by_annotation_label = {label: int(count) for label, count in annotation_label_rows}

    return DatasetStats(
        dataset_id=dataset_id,
        sample_count=len(samples),
        total_size=total_size,
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
