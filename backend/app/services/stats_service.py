from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.stats import DatasetStats
from app.services.dataset_service import get_dataset_or_404


def get_dataset_stats(session: Session, dataset_id: int) -> DatasetStats:
    get_dataset_or_404(session, dataset_id)
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()

    by_file_type: dict[str, int] = {}
    by_extension: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    total_size = 0

    for sample in samples:
        total_size += sample.file_size
        by_file_type[sample.file_type] = by_file_type.get(sample.file_type, 0) + 1
        by_extension[sample.extension] = by_extension.get(sample.extension, 0) + 1
        for tag in sample.tags:
            tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1

    return DatasetStats(
        dataset_id=dataset_id,
        sample_count=len(samples),
        total_size=total_size,
        by_file_type=by_file_type,
        by_extension=by_extension,
        tag_counts=tag_counts,
    )
