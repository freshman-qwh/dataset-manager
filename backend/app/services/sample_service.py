import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.sample import Sample
from app.models.annotation import Annotation
from app.models.tag import Tag
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
from app.services.tag_service import find_tag_by_name_or_alias, tag_matches_value, tag_to_read
from app.models.dataset import utc_now
from app.utils.file_types import detect_file_type, detect_mime_type
from app.utils.hashing import sha256_file
from app.utils.paths import relative_to_root, resolve_local_path

REVIEW_STATUSES = {"unlabeled", "in_review", "approved", "rejected"}
UNTAGGED_FILTER = "__untagged__"

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
        review_status=sample.review_status or "unlabeled",
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
    annotation_status: str | None = None,
    sample_ids: list[int] | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[Sample]:
    statement = select(Sample).where(Sample.dataset_id == dataset_id)
    duplicate_only = file_status == "duplicate"
    if file_type:
        statement = statement.where(Sample.file_type == file_type)
    if file_status and not duplicate_only:
        statement = statement.where(Sample.file_status == file_status)
    if split:
        if split == "unassigned":
            statement = statement.where(Sample.split.is_(None))
        else:
            statement = statement.where(Sample.split == split)
    if review_status:
        statement = statement.where(Sample.review_status == review_status)
    if sample_ids:
        statement = statement.where(Sample.id.in_(sample_ids))

    samples = session.exec(statement).all()

    if annotation_status:
        annotated_ids = set(
            session.exec(
                select(Annotation.sample_id).where(Annotation.dataset_id == dataset_id).distinct()
            ).all()
        )
        if annotation_status == "empty":
            samples = [sample for sample in samples if sample.id not in annotated_ids]
        elif annotation_status == "annotated":
            samples = [sample for sample in samples if sample.id in annotated_ids]

    if duplicate_only:
        duplicate_hashes = _duplicate_hashes(session, dataset_id)
        samples = [sample for sample in samples if sample.file_hash in duplicate_hashes]

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
        normalized_tag = tag.strip()
        if not normalized_tag:
            tag = None
        elif normalized_tag == UNTAGGED_FILTER:
            samples = [sample for sample in samples if not sample.tags]
            tag = None
        else:
            tag = normalized_tag

    if tag:
        samples = [
            sample
            for sample in samples
            if any(tag_matches_value(existing, tag) for existing in sample.tags)
        ]

    sort_field = sort_by if sort_by in SORTABLE_SAMPLE_FIELDS else "created_at"
    reverse = sort_order.lower() != "asc"
    sorted_samples = sorted(samples, key=lambda sample: _sample_sort_value(sample, sort_field), reverse=reverse)
    if duplicate_only:
        return _group_duplicate_samples(sorted_samples)
    return sorted_samples


def list_samples(
    session: Session,
    dataset_id: int,
    search: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    annotation_status: str | None = None,
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
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        annotation_status=annotation_status,
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


def get_sample_navigation(
    session: Session,
    dataset_id: int,
    sample_id: int | None = None,
    search: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    annotation_status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> SampleNavigationResponse:
    safe_sort_by = sort_by if sort_by in SORTABLE_SAMPLE_FIELDS else "created_at"
    safe_sort_order = "asc" if sort_order.lower() == "asc" else "desc"
    context_status = "duplicate" if file_status == "duplicate" else "normal"
    samples = get_filtered_samples(
        session,
        dataset_id,
        search=search,
        file_type="image",
        file_status=context_status,
        tag=tag,
        split=split,
        review_status=review_status,
        annotation_status=annotation_status,
        sort_by=safe_sort_by,
        sort_order=safe_sort_order,
    )
    # The duplicate status is a virtual filter. Keep the annotation workspace
    # constrained to normal image files after duplicate hash filtering.
    samples = [sample for sample in samples if sample.file_type == "image" and sample.file_status == "normal"]

    current_index: int | None = None
    if sample_id is not None:
        current_index = next((index for index, sample in enumerate(samples) if sample.id == sample_id), None)
    elif samples:
        current_index = 0

    current_sample = samples[current_index] if current_index is not None else None
    previous_sample = samples[current_index - 1] if current_index is not None and current_index > 0 else None
    next_sample = samples[current_index + 1] if current_index is not None and current_index < len(samples) - 1 else None

    return SampleNavigationResponse(
        current_sample=to_sample_read(current_sample) if current_sample else None,
        previous_sample=to_sample_read(previous_sample) if previous_sample else None,
        next_sample=to_sample_read(next_sample) if next_sample else None,
        current_index=current_index,
        total=len(samples),
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
    if "review_status" in updates and updates["review_status"] is not None:
        sample.review_status = _validate_review_status(updates["review_status"])
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
        if payload.review_status is not None:
            sample.review_status = _validate_review_status(payload.review_status)
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

    if payload.update_dataset_root:
        dataset.root_path = str(root)
        dataset.updated_at = utc_now()
        session.add(dataset)

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
    session.commit()


def _validate_review_status(value: str) -> str:
    normalized = value.strip() or "unlabeled"
    if normalized not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported review_status: {value}",
        )
    return normalized


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


def _duplicate_hashes(session: Session, dataset_id: int) -> set[str]:
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
    counts: dict[str, int] = {}
    for sample in samples:
        if sample.file_hash:
            counts[sample.file_hash] = counts.get(sample.file_hash, 0) + 1
    return {file_hash for file_hash, count in counts.items() if count > 1}


def _sample_sort_value(sample: Sample, sort_by: str):
    value = getattr(sample, sort_by)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.casefold()
    return value


def _group_duplicate_samples(samples: list[Sample]) -> list[Sample]:
    grouped: dict[str, list[Sample]] = {}
    group_order: list[str] = []
    for sample in samples:
        if sample.file_hash not in grouped:
            grouped[sample.file_hash] = []
            group_order.append(sample.file_hash)
        grouped[sample.file_hash].append(sample)
    return [sample for file_hash in group_order for sample in grouped[file_hash]]


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
