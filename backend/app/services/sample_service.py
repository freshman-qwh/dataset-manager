import csv
import json
from datetime import timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.sample import Sample
from app.models.tag import Tag
from app.schemas.sample import (
    BatchSampleUpdate,
    BatchSampleUpdateResult,
    SampleListResponse,
    SamplePreview,
    SampleRead,
    SampleUpdate,
)
from app.services.tag_service import find_tag_by_name_or_alias, tag_matches_value, tag_to_read
from app.models.dataset import utc_now

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
    tag: str | None = None,
    split: str | None = None,
    sample_ids: list[int] | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[Sample]:
    statement = select(Sample).where(Sample.dataset_id == dataset_id)
    if file_type:
        statement = statement.where(Sample.file_type == file_type)
    if split:
        if split == "unassigned":
            statement = statement.where(Sample.split.is_(None))
        else:
            statement = statement.where(Sample.split == split)
    if sample_ids:
        statement = statement.where(Sample.id.in_(sample_ids))

    samples = session.exec(statement).all()

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
        samples = [
            sample
            for sample in samples
            if any(tag_matches_value(existing, tag) for existing in sample.tags)
        ]

    sort_field = sort_by if sort_by in SORTABLE_SAMPLE_FIELDS else "created_at"
    reverse = sort_order.lower() != "asc"
    return sorted(samples, key=lambda sample: _sample_sort_value(sample, sort_field), reverse=reverse)


def list_samples(
    session: Session,
    dataset_id: int,
    search: str | None = None,
    file_type: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    page: int = 1,
    page_size: int = 60,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> SampleListResponse:
    safe_page_size = min(max(page_size, 1), 200)
    safe_sort_by = sort_by if sort_by in SORTABLE_SAMPLE_FIELDS else "created_at"
    safe_sort_order = "asc" if sort_order.lower() == "asc" else "desc"
    samples = get_filtered_samples(
        session,
        dataset_id,
        search=search,
        file_type=file_type,
        tag=tag,
        split=split,
        sort_by=safe_sort_by,
        sort_order=safe_sort_order,
    )
    page_count = max((len(samples) + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(max(page, 1), page_count)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return SampleListResponse(
        items=[to_sample_read(sample) for sample in samples[start:end]],
        total=len(samples),
        page=safe_page,
        page_size=safe_page_size,
        sort_by=safe_sort_by,
        sort_order=safe_sort_order,
    )


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


def batch_update_samples(
    session: Session,
    dataset_id: int,
    payload: BatchSampleUpdate,
) -> BatchSampleUpdateResult:
    statement = select(Sample).where(Sample.dataset_id == dataset_id, Sample.id.in_(payload.sample_ids))
    samples = session.exec(statement).all()

    add_tags = [_get_or_create_tag(session, dataset_id, name) for name in _clean_tag_names(payload.add_tags or [])]
    replace_tag_names = _clean_tag_names(payload.replace_tags or [])
    replace_tags = [_get_or_create_tag(session, dataset_id, name) for name in replace_tag_names]

    for sample in samples:
        if payload.split is not None:
            sample.split = payload.split or None
        if payload.replace_tags is not None:
            sample.tags = replace_tags.copy()
        elif add_tags:
            existing = {tag.name.casefold() for tag in sample.tags}
            sample.tags.extend([tag for tag in add_tags if tag.name.casefold() not in existing])
        sample.updated_at = utc_now().astimezone(timezone.utc)
        session.add(sample)

    session.commit()
    return BatchSampleUpdateResult(
        dataset_id=dataset_id,
        requested=len(payload.sample_ids),
        updated=len(samples),
        skipped=len(payload.sample_ids) - len(samples),
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


def _sample_sort_value(sample: Sample, sort_by: str):
    value = getattr(sample, sort_by)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.casefold()
    return value


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
