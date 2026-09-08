import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import and_, asc, desc, exists, false, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.sample import Sample, SampleTagLink
from app.models.tag import Tag
from app.core.workflow import ANNOTATION_PROGRESS_VALUES, REVIEW_STATUS_VALUES
from app.schemas.sample import (
    BatchSampleUpdate,
    BatchSampleUpdateResult,
    MissingSampleRepairRequest,
    MissingSampleRepairResult,
    SampleDeleteResult,
    SampleListResponse,
    SampleNavigationResponse,
    SamplePreview,
    SampleRepairRequest,
    SampleRead,
    SampleUpdate,
)
from app.services.dataset_service import get_dataset_or_404
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.tag_service import find_tag_by_name_or_alias, tag_to_read
from app.models.dataset import utc_now
from app.utils.file_types import detect_file_type, detect_mime_type
from app.utils.hashing import sha256_file
from app.utils.paths import relative_to_root, resolve_local_path

REVIEW_STATUSES = set(REVIEW_STATUS_VALUES)
ANNOTATION_PROGRESS_STATUSES = set(ANNOTATION_PROGRESS_VALUES)
UNTAGGED_FILTER = "__untagged__"
TAGGED_FILTER = "__tagged__"

SORTABLE_SAMPLE_FIELDS = {
    "created_at",
    "updated_at",
    "filename",
    "relative_path",
    "file_size",
    "extension",
    "file_type",
    "file_status",
    "split",
    "review_status",
    "annotation_progress",
}

TEXT_SORT_FIELDS = {
    "filename",
    "relative_path",
    "extension",
    "file_type",
    "file_status",
    "split",
    "review_status",
    "annotation_progress",
}


def to_sample_read(sample: Sample) -> SampleRead:
    tags = [tag_to_read(tag) for tag in sorted(sample.tags, key=lambda item: item.name)]
    return SampleRead(
        id=sample.id or 0,
        dataset_id=sample.dataset_id,
        filename=sample.filename,
        absolute_path=sample.absolute_path,
        relative_path=sample.relative_path,
        file_size=sample.file_size,
        extension=sample.extension,
        file_type=sample.file_type,
        mime_type=sample.mime_type,
        file_hash=sample.file_hash,
        file_status=sample.file_status,
        file_modified_at=sample.file_modified_at,
        last_scanned_at=sample.last_scanned_at,
        split=sample.split,
        annotation_progress=_normalize_annotation_progress(sample.annotation_progress),
        review_status=sample.review_status or "not_reviewed",
        notes=sample.notes,
        metadata=_metadata_from_json(sample.metadata_json),
        tags=tags,
        created_at=sample.created_at,
        updated_at=sample.updated_at,
    )


def get_filtered_samples(
    session: Session,
    dataset_id: int,
    search: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    annotation_progress: str | None = None,
    sample_ids: list[int] | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[Sample]:
    safe_sort_by = sort_by if sort_by in SORTABLE_SAMPLE_FIELDS else "created_at"
    safe_sort_order = "asc" if sort_order.lower() == "asc" else "desc"
    statement = _apply_sample_filters(
        select(Sample),
        session,
        dataset_id,
        search=search,
        file_type=file_type,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        annotation_progress=annotation_progress,
        sample_ids=sample_ids,
    )
    statement = statement.order_by(
        *_sample_order_clauses(
            safe_sort_by,
            safe_sort_order,
            duplicate_only=file_status == "duplicate",
        )
    ).options(selectinload(Sample.tags))
    return list(session.exec(statement).all())


def list_samples(
    session: Session,
    dataset_id: int,
    search: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    annotation_progress: str | None = None,
    page: int = 1,
    page_size: int = 60,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    thumbnail_prefetch: int = 0,
) -> SampleListResponse:
    safe_page_size = min(max(page_size, 1), 200)
    safe_sort_by = sort_by if sort_by in SORTABLE_SAMPLE_FIELDS else "created_at"
    safe_sort_order = "asc" if sort_order.lower() == "asc" else "desc"
    filtered_ids = _apply_sample_filters(
        select(Sample.id),
        session,
        dataset_id,
        search=search,
        file_type=file_type,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        annotation_progress=annotation_progress,
    )
    total = int(session.exec(select(func.count()).select_from(filtered_ids.subquery())).one())
    page_count = max((total + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(max(page, 1), page_count)
    statement = _apply_sample_filters(
        select(Sample),
        session,
        dataset_id,
        search=search,
        file_type=file_type,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        annotation_progress=annotation_progress,
    )
    statement = (
        statement.order_by(
            *_sample_order_clauses(
                safe_sort_by,
                safe_sort_order,
                duplicate_only=file_status == "duplicate",
            )
        )
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
        .options(selectinload(Sample.tags))
    )
    samples = list(session.exec(statement).all())
    thumbnail_prefetch_sample_ids: list[int] = []
    safe_thumbnail_prefetch = min(max(thumbnail_prefetch, 0), 12)
    if safe_thumbnail_prefetch:
        page_start = (safe_page - 1) * safe_page_size
        window_start = max(page_start - safe_thumbnail_prefetch, 0)
        window_end = min(page_start + safe_page_size + safe_thumbnail_prefetch, total)
        prefetch_statement = _apply_sample_filters(
            select(Sample.id, Sample.file_type, Sample.file_status),
            session,
            dataset_id,
            search=search,
            file_type=file_type,
            file_status=file_status,
            tag=tag,
            split=split,
            review_status=review_status,
            annotation_progress=annotation_progress,
        )
        prefetch_statement = (
            prefetch_statement.order_by(
                *_sample_order_clauses(
                    safe_sort_by,
                    safe_sort_order,
                    duplicate_only=file_status == "duplicate",
                )
            )
            .offset(window_start)
            .limit(window_end - window_start)
        )
        current_ids = {sample.id for sample in samples if sample.id is not None}
        thumbnail_prefetch_sample_ids = [
            int(row[0])
            for row in session.exec(prefetch_statement).all()
            if row[0] not in current_ids
            and row[1] == "image"
            and row[2] == "normal"
        ]
    return SampleListResponse(
        items=[to_sample_read(sample) for sample in samples],
        total=total,
        page=safe_page,
        page_size=safe_page_size,
        sort_by=safe_sort_by,
        sort_order=safe_sort_order,
        thumbnail_prefetch_sample_ids=thumbnail_prefetch_sample_ids,
    )


def get_sample_navigation(
    session: Session,
    dataset_id: int,
    sample_id: int | None = None,
    search: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    annotation_progress: str | None = None,
    queue_scope: str = "current_filter",
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> SampleNavigationResponse:
    safe_sort_by = sort_by if sort_by in SORTABLE_SAMPLE_FIELDS else "created_at"
    safe_sort_order = "asc" if sort_order.lower() == "asc" else "desc"
    safe_queue_scope = (
        queue_scope
        if queue_scope in {"all_pending", "current_filter", "current_split"}
        else "current_filter"
    )
    context_status = (
        "duplicate"
        if safe_queue_scope == "current_filter" and file_status == "duplicate"
        else "normal"
    )
    queue_split = split
    if safe_queue_scope == "current_split" and not queue_split and sample_id is not None:
        current_sample = session.get(Sample, sample_id)
        if current_sample and current_sample.dataset_id == dataset_id:
            queue_split = current_sample.split or "unassigned"

    queue_file_status = context_status if safe_queue_scope == "current_filter" else "normal"
    queue_split_filter = (
        queue_split
        if safe_queue_scope == "current_split"
        else split if safe_queue_scope == "current_filter" else None
    )
    order_clauses = _sample_order_clauses(
        safe_sort_by,
        safe_sort_order,
        duplicate_only=queue_file_status == "duplicate",
    )
    filter_options = {
        "search": search if safe_queue_scope == "current_filter" else None,
        "file_type": "image",
        "file_status": queue_file_status,
        "tag": tag if safe_queue_scope == "current_filter" else None,
        "split": queue_split_filter,
        "review_status": review_status if safe_queue_scope == "current_filter" else None,
        "annotation_progress": annotation_progress if safe_queue_scope == "current_filter" else None,
        "pending_only": safe_queue_scope in {"all_pending", "current_split"},
    }
    if queue_file_status != "duplicate":
        current_index, total, current_id, previous_id, next_id = _get_indexed_navigation_ids(
            session,
            dataset_id,
            sample_id,
            safe_sort_by,
            safe_sort_order,
            filter_options,
        )
    else:
        ranked_statement = _apply_sample_filters(
            select(
                Sample.id.label("sample_id"),
                func.row_number().over(order_by=order_clauses).label("position"),
                func.lag(Sample.id).over(order_by=order_clauses).label("previous_id"),
                func.lead(Sample.id).over(order_by=order_clauses).label("next_id"),
                func.count().over().label("total"),
            ),
            session,
            dataset_id,
            **filter_options,
        )
        # Duplicate is a virtual filter; annotation navigation still excludes
        # missing and unreadable image records from the resulting queue.
        ranked_statement = ranked_statement.where(Sample.file_status == "normal")
        ranked = ranked_statement.subquery()
        row_statement = select(
            ranked.c.sample_id,
            ranked.c.position,
            ranked.c.previous_id,
            ranked.c.next_id,
            ranked.c.total,
        )
        if sample_id is None:
            row_statement = row_statement.order_by(ranked.c.position).limit(1)
        else:
            row_statement = row_statement.where(ranked.c.sample_id == sample_id)
        row = session.exec(row_statement).first()
        current_index = None
        total = 0
        current_id = None
        previous_id = None
        next_id = None
        if row is not None:
            current_id = int(row[0])
            current_index = int(row[1]) - 1
            previous_id = int(row[2]) if row[2] is not None else None
            next_id = int(row[3]) if row[3] is not None else None
            total = int(row[4])
        else:
            total_statement = _apply_sample_filters(
                select(func.count(Sample.id)),
                session,
                dataset_id,
                **filter_options,
            ).where(Sample.file_status == "normal")
            total = int(session.exec(total_statement).one())

    samples_by_id: dict[int, Sample] = {}
    neighbor_ids = [item_id for item_id in (current_id, previous_id, next_id) if item_id is not None]
    if neighbor_ids:
        neighbor_statement = (
            select(Sample)
            .where(Sample.id.in_(neighbor_ids))
            .options(selectinload(Sample.tags))
        )
        samples_by_id = {
            sample.id: sample
            for sample in session.exec(neighbor_statement).all()
            if sample.id is not None
        }
    current_sample = samples_by_id.get(current_id) if current_id is not None else None
    previous_sample = samples_by_id.get(previous_id) if previous_id is not None else None
    next_sample = samples_by_id.get(next_id) if next_id is not None else None

    return SampleNavigationResponse(
        current_sample=to_sample_read(current_sample) if current_sample else None,
        previous_sample=to_sample_read(previous_sample) if previous_sample else None,
        next_sample=to_sample_read(next_sample) if next_sample else None,
        current_index=current_index,
        total=total,
        remaining=max(total - (1 if current_index is not None else 0), 0),
        queue_scope=safe_queue_scope,
        sort_by=safe_sort_by,
        sort_order=safe_sort_order,
    )


def _apply_sample_filters(
    statement,
    session: Session,
    dataset_id: int,
    *,
    search: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    annotation_progress: str | None = None,
    sample_ids: list[int] | None = None,
    pending_only: bool = False,
):
    statement = statement.where(Sample.dataset_id == dataset_id)
    if file_type:
        statement = statement.where(Sample.file_type == file_type)
    if file_status == "duplicate":
        duplicate_hashes = (
            select(Sample.file_hash)
            .where(
                Sample.dataset_id == dataset_id,
                Sample.file_hash != "",
            )
            .group_by(Sample.file_hash)
            .having(func.count(Sample.id) > 1)
        )
        statement = statement.where(Sample.file_hash.in_(duplicate_hashes))
    elif file_status:
        statement = statement.where(Sample.file_status == file_status)
    if split == "unassigned":
        statement = statement.where(Sample.split.is_(None))
    elif split:
        statement = statement.where(Sample.split == split)
    if review_status:
        statement = statement.where(Sample.review_status == review_status)
    if pending_only:
        statement = statement.where(
            or_(
                Sample.annotation_progress.in_(("not_started", "in_progress")),
                Sample.annotation_progress.is_(None),
                ~Sample.annotation_progress.in_(tuple(ANNOTATION_PROGRESS_STATUSES)),
            )
        )
    elif annotation_progress:
        statement = statement.where(Sample.annotation_progress == annotation_progress)
    if sample_ids:
        statement = statement.where(Sample.id.in_(sample_ids))

    normalized_search = (search or "").strip().casefold()
    if normalized_search:
        escaped = (
            normalized_search
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        statement = statement.where(
            or_(
                func.lower(Sample.filename).like(pattern, escape="\\"),
                func.lower(Sample.relative_path).like(pattern, escape="\\"),
                func.lower(Sample.file_hash).like(pattern, escape="\\"),
            )
        )

    normalized_tag = (tag or "").strip()
    tag_link_exists = exists(
        select(SampleTagLink.sample_id).where(SampleTagLink.sample_id == Sample.id)
    )
    if normalized_tag == UNTAGGED_FILTER:
        statement = statement.where(~tag_link_exists)
    elif normalized_tag == TAGGED_FILTER:
        statement = statement.where(tag_link_exists)
    elif normalized_tag:
        matched_tag = find_tag_by_name_or_alias(session, dataset_id, normalized_tag)
        if matched_tag is None or matched_tag.id is None:
            statement = statement.where(false())
        else:
            statement = statement.where(
                exists(
                    select(SampleTagLink.sample_id).where(
                        SampleTagLink.sample_id == Sample.id,
                        SampleTagLink.tag_id == matched_tag.id,
                    )
                )
            )
    return statement


def _get_indexed_navigation_ids(
    session: Session,
    dataset_id: int,
    sample_id: int | None,
    sort_by: str,
    sort_order: str,
    filter_options: dict[str, object],
) -> tuple[int | None, int, int | None, int | None, int | None]:
    def filtered(statement):
        return _apply_sample_filters(
            statement,
            session,
            dataset_id,
            **filter_options,
        )

    total = int(session.exec(filtered(select(func.count(Sample.id)))).one())
    order_clauses = _sample_order_clauses(sort_by, sort_order)
    if sample_id is None:
        current_id = session.exec(
            filtered(select(Sample.id)).order_by(*order_clauses).limit(1)
        ).first()
        if current_id is None:
            return None, total, None, None, None
        next_id = session.exec(
            filtered(select(Sample.id))
            .where(
                _sample_relative_condition(
                    sort_by,
                    sort_order,
                    _sample_sort_value_for_id(session, int(current_id), sort_by),
                    int(current_id),
                    before=False,
                )
            )
            .order_by(*order_clauses)
            .limit(1)
        ).first()
        return 0, total, int(current_id), None, int(next_id) if next_id is not None else None

    current_value = session.exec(
        filtered(select(getattr(Sample, sort_by))).where(Sample.id == sample_id)
    ).first()
    if current_value is None and not session.exec(
        filtered(select(Sample.id)).where(Sample.id == sample_id)
    ).first():
        return None, total, None, None, None
    before_condition = _sample_relative_condition(
        sort_by,
        sort_order,
        current_value,
        sample_id,
        before=True,
    )
    after_condition = _sample_relative_condition(
        sort_by,
        sort_order,
        current_value,
        sample_id,
        before=False,
    )
    current_index = int(
        session.exec(
            filtered(select(func.count(Sample.id))).where(before_condition)
        ).one()
    )
    reverse_order = "desc" if sort_order == "asc" else "asc"
    previous_id = session.exec(
        filtered(select(Sample.id))
        .where(before_condition)
        .order_by(*_sample_order_clauses(sort_by, reverse_order))
        .limit(1)
    ).first()
    next_id = session.exec(
        filtered(select(Sample.id))
        .where(after_condition)
        .order_by(*order_clauses)
        .limit(1)
    ).first()
    return (
        current_index,
        total,
        sample_id,
        int(previous_id) if previous_id is not None else None,
        int(next_id) if next_id is not None else None,
    )


def _sample_sort_value_for_id(
    session: Session,
    sample_id: int,
    sort_by: str,
):
    return session.exec(
        select(getattr(Sample, sort_by)).where(Sample.id == sample_id)
    ).one()


def _sample_relative_condition(
    sort_by: str,
    sort_order: str,
    current_value,
    current_id: int,
    *,
    before: bool,
):
    column = getattr(Sample, sort_by)
    expression = func.lower(column) if sort_by in TEXT_SORT_FIELDS else column
    normalized_value = (
        current_value.casefold()
        if isinstance(current_value, str) and sort_by in TEXT_SORT_FIELDS
        else current_value
    )
    id_before = Sample.id < current_id if sort_order == "asc" else Sample.id > current_id
    id_after = Sample.id > current_id if sort_order == "asc" else Sample.id < current_id

    if normalized_value is None:
        same_value_before = and_(column.is_(None), id_before)
        same_value_after = and_(column.is_(None), id_after)
        if sort_order == "asc":
            return same_value_before if before else or_(column.is_not(None), same_value_after)
        return or_(column.is_not(None), same_value_before) if before else same_value_after

    same_value_before = and_(expression == normalized_value, id_before)
    same_value_after = and_(expression == normalized_value, id_after)
    if sort_order == "asc":
        if before:
            return or_(column.is_(None), expression < normalized_value, same_value_before)
        return or_(expression > normalized_value, same_value_after)
    if before:
        return or_(expression > normalized_value, same_value_before)
    return or_(column.is_(None), expression < normalized_value, same_value_after)


def _sample_order_clauses(
    sort_by: str,
    sort_order: str,
    *,
    duplicate_only: bool = False,
):
    sort_column = getattr(Sample, sort_by)
    sort_expression = func.lower(sort_column) if sort_by in TEXT_SORT_FIELDS else sort_column
    direction = asc if sort_order == "asc" else desc
    clauses = []
    if duplicate_only:
        clauses.append(asc(Sample.file_hash))
    clauses.extend((direction(sort_expression), direction(Sample.id)))
    return clauses


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
    existing = find_tag_by_name_or_alias(session, dataset_id, clean_name)
    if existing:
        return existing

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
    if "review_status" in updates and updates["review_status"] is not None:
        sample.review_status = _validate_review_status(updates["review_status"])
    if "annotation_progress" in updates and updates["annotation_progress"] is not None:
        sample.annotation_progress = _validate_annotation_progress(updates["annotation_progress"])
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
    if updates:
        bump_dataset_revision(session, sample.dataset_id)
    session.commit()
    session.refresh(sample)
    return to_sample_read(sample)


def batch_update_samples(
    session: Session,
    dataset_id: int,
    payload: BatchSampleUpdate,
) -> BatchSampleUpdateResult:
    statement = select(Sample).where(Sample.dataset_id == dataset_id, Sample.id.in_(payload.sample_ids))
    samples = session.exec(statement).all()

    if not samples:
        return BatchSampleUpdateResult(
            dataset_id=dataset_id,
            requested=len(payload.sample_ids),
            updated=0,
            skipped=len(payload.sample_ids),
        )

    add_tags = [_get_or_create_tag(session, dataset_id, name) for name in _clean_tag_names(payload.add_tags or [])]
    replace_tag_names = _clean_tag_names(payload.replace_tags or [])
    replace_tags = [_get_or_create_tag(session, dataset_id, name) for name in replace_tag_names]

    for sample in samples:
        if payload.split is not None:
            sample.split = payload.split or None
        if payload.review_status is not None:
            sample.review_status = _validate_review_status(payload.review_status)
        if payload.annotation_progress is not None:
            sample.annotation_progress = _validate_annotation_progress(payload.annotation_progress)
        if payload.replace_tags is not None:
            sample.tags = replace_tags.copy()
        elif add_tags:
            existing = {tag.name.casefold() for tag in sample.tags}
            sample.tags.extend([tag for tag in add_tags if tag.name.casefold() not in existing])
        sample.updated_at = utc_now().astimezone(timezone.utc)
        session.add(sample)

    bump_dataset_revision(session, dataset_id)
    session.commit()
    return BatchSampleUpdateResult(
        dataset_id=dataset_id,
        requested=len(payload.sample_ids),
        updated=len(samples),
        skipped=len(payload.sample_ids) - len(samples),
    )


def delete_sample(session: Session, sample_id: int) -> SampleDeleteResult:
    sample = get_sample_or_404(session, sample_id)
    dataset_id = sample.dataset_id
    _delete_samples(session, [sample])
    return SampleDeleteResult(dataset_id=dataset_id, requested=1, deleted=1, skipped=0)


def delete_samples(session: Session, dataset_id: int, sample_ids: list[int]) -> SampleDeleteResult:
    statement = select(Sample).where(Sample.dataset_id == dataset_id, Sample.id.in_(sample_ids))
    samples = session.exec(statement).all()
    _delete_samples(session, samples)
    return SampleDeleteResult(
        dataset_id=dataset_id,
        requested=len(sample_ids),
        deleted=len(samples),
        skipped=len(sample_ids) - len(samples),
    )


def repair_sample_file(session: Session, sample_id: int, payload: SampleRepairRequest) -> SampleRead:
    sample = get_sample_or_404(session, sample_id)
    dataset = get_dataset_or_404(session, sample.dataset_id)
    path = resolve_local_path(payload.file_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File does not exist: {path}")
    _ensure_no_path_conflict(session, sample.dataset_id, path, sample.id)
    _apply_path_metadata(sample, path, dataset.root_path)
    session.add(sample)
    bump_dataset_revision(session, sample.dataset_id)
    _commit_or_conflict(session)
    session.refresh(sample)
    return to_sample_read(sample)


def repair_missing_samples(
    session: Session,
    dataset_id: int,
    payload: MissingSampleRepairRequest,
) -> MissingSampleRepairResult:
    dataset = get_dataset_or_404(session, dataset_id)
    root = resolve_local_path(payload.root_path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Folder does not exist: {root}")

    samples = session.exec(
        select(Sample).where(
            Sample.dataset_id == dataset_id,
            Sample.file_status.in_(["missing", "permission_denied"]),
        )
    ).all()
    checked = len(samples)
    repaired = 0
    errors: list[str] = []

    for sample in samples:
        candidate = root / sample.relative_path
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            _ensure_no_path_conflict(session, dataset_id, candidate, sample.id)
            _apply_path_metadata(sample, candidate, str(root))
            session.add(sample)
            repaired += 1
        except HTTPException as exc:
            errors.append(f"{sample.relative_path}: {exc.detail}")
        except OSError as exc:
            errors.append(f"{sample.relative_path}: {exc}")

    root_changed = payload.update_dataset_root and dataset.root_path != str(root)
    if payload.update_dataset_root:
        dataset.root_path = str(root)
        dataset.updated_at = utc_now()
        session.add(dataset)

    if repaired or root_changed:
        bump_dataset_revision(session, dataset_id)
    _commit_or_conflict(session)
    return MissingSampleRepairResult(
        dataset_id=dataset_id,
        root_path=str(root),
        checked=checked,
        repaired=repaired,
        skipped=checked - repaired,
        errors=errors[:50],
    )


def get_sample_preview(sample: Sample) -> SamplePreview:
    if sample.file_status == "missing":
        return SamplePreview(
            sample_id=sample.id or 0,
            file_type=sample.file_type,
            filename=sample.filename,
            error="Sample file is missing from disk.",
        )

    if sample.file_type != "table":
        return SamplePreview(
            sample_id=sample.id or 0,
            file_type=sample.file_type,
            filename=sample.filename,
            file_url=f"/api/samples/{sample.id}/file",
        )

    path = Path(sample.absolute_path)
    if not path.exists() or not path.is_file():
        return SamplePreview(
            sample_id=sample.id or 0,
            file_type=sample.file_type,
            filename=sample.filename,
            error="Sample file is missing from disk.",
        )

    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as file:
            reader = csv.DictReader(file)
            columns = list(reader.fieldnames or [])
            rows: list[dict[str, str]] = []
            for index, row in enumerate(reader):
                if index >= 30:
                    break
                rows.append({key: str(value or "") for key, value in row.items()})
    except OSError as exc:
        return SamplePreview(
            sample_id=sample.id or 0,
            file_type=sample.file_type,
            filename=sample.filename,
            error=str(exc),
        )

    return SamplePreview(
        sample_id=sample.id or 0,
        file_type=sample.file_type,
        filename=sample.filename,
        columns=columns,
        rows=rows,
        preview_row_count=len(rows),
    )


def _delete_samples(session: Session, samples: list[Sample]) -> None:
    from app.services import annotation_service

    annotation_service.delete_sample_annotations(session, [sample.id for sample in samples if sample.id is not None])
    for sample in samples:
        # Metadata-only delete: detach tag links and remove the database record.
        sample.tags.clear()
        session.add(sample)
        session.delete(sample)
    if samples:
        bump_dataset_revision(session, samples[0].dataset_id)
    session.commit()


def _validate_review_status(value: str) -> str:
    normalized = value.strip() or "not_reviewed"
    if normalized not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported review_status: {value}",
        )
    return normalized


def _validate_annotation_progress(value: str) -> str:
    normalized = value.strip() or "not_started"
    if normalized not in ANNOTATION_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported annotation_progress: {value}",
        )
    return normalized


def _normalize_annotation_progress(value: str | None):
    normalized = value or "not_started"
    return normalized if normalized in ANNOTATION_PROGRESS_STATUSES else "not_started"


def _apply_path_metadata(sample: Sample, path: Path, root_path: str | None) -> None:
    file_type = detect_file_type(path)
    if not file_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported file type: {path.suffix}")

    root = resolve_local_path(root_path) if root_path else path.parent.resolve()
    stat = path.stat()
    sample.filename = path.name
    sample.absolute_path = str(path.resolve())
    sample.relative_path = relative_to_root(path.resolve(), root)
    sample.file_size = stat.st_size
    sample.extension = path.suffix.lower()
    sample.file_type = file_type
    sample.mime_type = detect_mime_type(path)
    sample.file_hash = sha256_file(path)
    sample.file_status = "normal"
    sample.file_modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    sample.last_scanned_at = utc_now()
    sample.updated_at = utc_now()


def _ensure_no_path_conflict(session: Session, dataset_id: int, path: Path, current_sample_id: int | None) -> None:
    absolute_path = str(path.resolve())
    existing = session.exec(
        select(Sample).where(Sample.dataset_id == dataset_id, Sample.absolute_path == absolute_path)
    ).first()
    if existing and existing.id != current_sample_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Another sample already uses this file path: {absolute_path}",
        )


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sample path already exists.") from exc


def _clean_tag_names(raw_names: list[str]) -> list[str]:
    unique_names = []
    seen = set()
    for raw_name in raw_names:
        name = raw_name.strip().strip('"').strip("'")
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            unique_names.append(name)
    return unique_names


def _metadata_from_json(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
