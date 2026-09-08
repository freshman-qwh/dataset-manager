from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import case, desc, func, true
from sqlmodel import Session, select

from app.models.dataset import Dataset
from app.models.sample import Sample
from app.schemas.duplicates import DuplicateGroup, DuplicateReport, DuplicateSample

TRAINING_SPLITS = ("train", "val", "test")
SAMPLES_PER_GROUP = 20


def get_duplicate_report(
    session: Session,
    dataset_id: int,
    *,
    leakage_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> DuplicateReport:
    safe_page_size = min(max(page_size, 1), 100)
    normalized_split = func.trim(func.coalesce(Sample.split, ""))
    grouped_hashes = (
        select(
            Sample.file_hash.label("file_hash"),
            func.count(Sample.id).label("sample_count"),
            func.count(
                func.distinct(
                    case(
                        (normalized_split.in_(TRAINING_SPLITS), normalized_split),
                        else_=None,
                    )
                )
            ).label("training_split_count"),
        )
        .where(
            Sample.dataset_id == dataset_id,
            Sample.file_hash != "",
        )
        .group_by(Sample.file_hash)
        .having(func.count(Sample.id) > 1)
        .subquery()
    )
    is_cross_split = grouped_hashes.c.training_split_count >= 2
    summary = session.exec(
        select(
            Dataset.id,
            func.count(grouped_hashes.c.file_hash).label("group_count"),
            func.coalesce(func.sum(grouped_hashes.c.sample_count), 0).label("sample_count"),
            func.coalesce(func.sum(case((is_cross_split, 1), else_=0)), 0).label(
                "cross_split_group_count"
            ),
            func.coalesce(
                func.sum(case((is_cross_split, grouped_hashes.c.sample_count), else_=0)),
                0,
            ).label("cross_split_sample_count"),
        )
        .select_from(Dataset)
        .outerjoin(grouped_hashes, true())
        .where(Dataset.id == dataset_id)
        .group_by(Dataset.id)
    ).first()
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} was not found.",
        )
    group_count = int(summary[1])
    duplicate_sample_count = int(summary[2])
    cross_split_group_count = int(summary[3])
    cross_split_sample_count = int(summary[4])
    filtered_group_count = cross_split_group_count if leakage_only else group_count
    page_count = max((filtered_group_count + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(max(page, 1), page_count)

    group_statement = select(
        grouped_hashes.c.file_hash,
        grouped_hashes.c.sample_count,
        grouped_hashes.c.training_split_count,
    )
    if leakage_only:
        group_statement = group_statement.where(is_cross_split)
    paged_groups = (
        group_statement.order_by(
            desc(is_cross_split),
            desc(grouped_hashes.c.sample_count),
            grouped_hashes.c.file_hash,
        )
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
        .subquery()
    )
    displayed_split = func.coalesce(
        func.nullif(func.trim(func.coalesce(Sample.split, "")), ""),
        "unassigned",
    )
    paged_cross_split = paged_groups.c.training_split_count >= 2
    split_rows = session.exec(
        select(
            paged_groups.c.file_hash,
            paged_groups.c.sample_count,
            paged_groups.c.training_split_count,
            displayed_split.label("split_name"),
            func.count(Sample.id).label("split_count"),
        )
        .select_from(paged_groups)
        .join(
            Sample,
            (Sample.dataset_id == dataset_id)
            & (Sample.file_hash == paged_groups.c.file_hash),
        )
        .group_by(
            paged_groups.c.file_hash,
            paged_groups.c.sample_count,
            paged_groups.c.training_split_count,
            displayed_split,
        )
        .order_by(
            desc(paged_cross_split),
            desc(paged_groups.c.sample_count),
            paged_groups.c.file_hash,
            displayed_split,
        )
    ).all()
    group_rows: list[tuple[str, int, int]] = []
    split_counts_by_hash: dict[str, dict[str, int]] = defaultdict(dict)
    for row in split_rows:
        file_hash = str(row[0])
        if file_hash not in split_counts_by_hash:
            group_rows.append((file_hash, int(row[1]), int(row[2])))
        split_counts_by_hash[file_hash][str(row[3])] = int(row[4])
    page_hashes = [row[0] for row in group_rows]
    samples = []
    if page_hashes:
        ranked_sample_ids = (
            select(
                Sample.id.label("sample_id"),
                func.row_number()
                .over(
                    partition_by=Sample.file_hash,
                    order_by=(Sample.relative_path, Sample.id),
                )
                .label("group_row_number"),
            )
            .where(
                Sample.dataset_id == dataset_id,
                Sample.file_hash.in_(page_hashes),
            )
            .subquery()
        )
        samples = session.exec(
            select(Sample)
            .join(ranked_sample_ids, ranked_sample_ids.c.sample_id == Sample.id)
            .where(ranked_sample_ids.c.group_row_number <= SAMPLES_PER_GROUP)
            .order_by(Sample.file_hash, Sample.relative_path)
        ).all()
    groups: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        if sample.file_hash:
            groups[sample.file_hash].append(sample)

    duplicate_groups: list[DuplicateGroup] = []
    for row in group_rows:
        file_hash = row[0]
        group_samples = groups[file_hash]
        split_counts = split_counts_by_hash[file_hash]
        training_splits = sorted(
            {split_name for split_name in split_counts if split_name in TRAINING_SPLITS},
            key=TRAINING_SPLITS.index,
        )
        duplicate_groups.append(
            DuplicateGroup(
                file_hash=file_hash,
                count=int(row[1]),
                cross_split=int(row[2]) >= 2,
                training_splits=training_splits,
                split_counts=dict(sorted(split_counts.items())),
                samples_truncated=int(row[1]) > len(group_samples),
                samples=[
                    DuplicateSample(
                        id=sample.id or 0,
                        filename=sample.filename,
                        relative_path=sample.relative_path,
                        file_size=sample.file_size,
                        file_status=sample.file_status,
                        split=sample.split,
                        annotation_progress=sample.annotation_progress or "not_started",
                        review_status=sample.review_status or "not_reviewed",
                    )
                    for sample in group_samples
                ],
            )
        )

    return DuplicateReport(
        dataset_id=dataset_id,
        group_count=group_count,
        duplicate_sample_count=duplicate_sample_count,
        cross_split_group_count=cross_split_group_count,
        cross_split_sample_count=cross_split_sample_count,
        filtered_group_count=filtered_group_count,
        leakage_only=leakage_only,
        page=safe_page,
        page_size=safe_page_size,
        has_previous=safe_page > 1,
        has_next=safe_page * safe_page_size < filtered_group_count,
        groups=duplicate_groups,
    )
