from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.duplicates import DuplicateGroup, DuplicateReport
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import to_sample_read


def get_duplicate_report(session: Session, dataset_id: int) -> DuplicateReport:
    get_dataset_or_404(session, dataset_id)
    duplicate_hashes = (
        select(Sample.file_hash)
        .where(
            Sample.dataset_id == dataset_id,
            Sample.file_hash != "",
        )
        .group_by(Sample.file_hash)
        .having(func.count(Sample.id) > 1)
    )
    samples = session.exec(
        select(Sample)
        .where(
            Sample.dataset_id == dataset_id,
            Sample.file_hash.in_(duplicate_hashes),
        )
        .order_by(Sample.file_hash, Sample.relative_path)
        .options(selectinload(Sample.tags))
    ).all()
    groups: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        if sample.file_hash:
            groups[sample.file_hash].append(sample)

    duplicate_groups = [
        DuplicateGroup(
            file_hash=file_hash,
            count=len(group_samples),
            samples=[to_sample_read(sample) for sample in sorted(group_samples, key=lambda item: item.relative_path)],
        )
        for file_hash, group_samples in groups.items()
        if len(group_samples) > 1
    ]
    duplicate_groups.sort(key=lambda group: group.count, reverse=True)

    return DuplicateReport(
        dataset_id=dataset_id,
        group_count=len(duplicate_groups),
        duplicate_sample_count=sum(group.count for group in duplicate_groups),
        groups=duplicate_groups,
    )
