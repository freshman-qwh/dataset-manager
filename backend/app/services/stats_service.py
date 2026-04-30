from sqlmodel import Session, select

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
    hash_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    total_size = 0

    for sample in samples:
        total_size += sample.file_size
        by_file_type[sample.file_type] = by_file_type.get(sample.file_type, 0) + 1
        by_extension[sample.extension] = by_extension.get(sample.extension, 0) + 1
        by_status[sample.file_status] = by_status.get(sample.file_status, 0) + 1
        split = sample.split or "unassigned"
        by_split[split] = by_split.get(split, 0) + 1
        hash_counts[sample.file_hash] = hash_counts.get(sample.file_hash, 0) + 1
        for tag in sample.tags:
            tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1

    duplicate_counts = [count for count in hash_counts.values() if count > 1]

    return DatasetStats(
        dataset_id=dataset_id,
        sample_count=len(samples),
        total_size=total_size,
        by_file_type=by_file_type,
        by_extension=by_extension,
        by_status=by_status,
        by_split=by_split,
        tag_counts=tag_counts,
        duplicate_groups=len(duplicate_counts),
        duplicate_samples=sum(duplicate_counts),
    )
