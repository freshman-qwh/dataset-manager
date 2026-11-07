"""Query registered metadata only; these helpers never inspect or mutate disk files."""
import re

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, select

from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.schemas.daily_tools import (
    CoverageAxis, CoverageCell, CoverageCounts, CoverageRead, CoverageSamplesRead,
    CoverageStatus, FilenameLookupRead, FilenameLookupResult, LookupCandidate,
)
from app.services.dataset_card_service import effective_image_label
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import to_sample_read


def _entry(value: str) -> str:
    value = value.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value.replace("\\", "/")


def _lookup_condition(entry: str) -> ColumnElement[bool]:
    absolute = func.replace(Sample.absolute_path, "\\", "/")
    windows = or_(func.substr(absolute, 2, 1) == ":", func.substr(absolute, 1, 2) == "//")
    column = absolute if entry.startswith("/") or re.match(r"^[A-Za-z]:", entry) else (
        func.replace(Sample.relative_path, "\\", "/") if "/" in entry else Sample.filename
    )
    # SQL lower() folds ASCII, matching normal Windows drive/path conventions;
    # POSIX records retain exact case and wildcard characters are always literal.
    return or_(column == entry, and_(windows, func.lower(column) == func.lower(entry)))


def lookup_candidates(session: Session, dataset_id: int, entry: str, *, page: int = 1,
                      page_size: int = 5) -> FilenameLookupResult:
    get_dataset_or_404(session, dataset_id)
    entry = _entry(entry)
    scope = [Sample.dataset_id == dataset_id, Sample.file_type == "image", _lookup_condition(entry)]
    total = int(session.exec(select(func.count(Sample.id)).where(*scope)).one()) if entry else 0
    page = min(page, max((total + page_size - 1) // page_size, 1))
    rows = session.exec(select(Sample.id, Sample.filename, Sample.relative_path,
        Sample.absolute_path, Sample.file_status, Sample.file_hash).where(*scope)
        .order_by(Sample.absolute_path, Sample.id).offset((page - 1) * page_size).limit(page_size)).all() if entry else []
    return FilenameLookupResult(entry=entry, total=total, page=page, page_size=page_size,
        candidates=[LookupCandidate(**row._mapping) for row in rows])


def lookup_filenames(session: Session, dataset_id: int, entries: list[str]) -> FilenameLookupRead:
    get_dataset_or_404(session, dataset_id)
    seen: set[str] = set()
    results: list[FilenameLookupResult] = []
    duplicates = blanks = 0
    for raw in entries:
        value = _entry(raw)
        if not value:
            blanks += 1
        elif value in seen:
            duplicates += 1
        else:
            seen.add(value)
            results.append(lookup_candidates(session, dataset_id, value))
    return FilenameLookupRead(dataset_id=dataset_id, duplicate_count=duplicates,
        blank_count=blanks, results=results)


def _coverage_status(policy_version: int) -> ColumnElement[str]:
    label = effective_image_label(policy_version)
    stale = and_(Sample.triage_status.in_(("ok", "ng")), or_(
        Sample.triaged_file_hash.is_(None), Sample.triaged_file_hash != Sample.file_hash,
        Sample.triage_policy_version.is_(None), Sample.triage_policy_version != policy_version,
    ))
    return case((Sample.file_status != "normal", "unavailable"), (stale, "stale"),
        (label == "normal", "normal"), (label == "anomaly", "anomaly"),
        (label == "pending", "pending"), else_="untriaged")


def read_coverage(session: Session, dataset_id: int) -> CoverageRead:
    dataset = get_dataset_or_404(session, dataset_id)
    categories = session.exec(select(DatasetCategory).where(DatasetCategory.dataset_id == dataset_id)
        .order_by(func.lower(DatasetCategory.name), DatasetCategory.id)).all()
    batches = session.exec(select(DatasetBatch).where(DatasetBatch.dataset_id == dataset_id)
        .order_by(func.lower(DatasetBatch.name), DatasetBatch.id)).all()
    status = _coverage_status(dataset.triage_policy_version)
    rows = session.exec(select(Sample.category_id, Sample.batch_id, status.label("status"),
        func.count(Sample.id).label("count")).where(Sample.dataset_id == dataset_id, Sample.file_type == "image")
        .group_by(Sample.category_id, Sample.batch_id, status)).all()
    grouped: dict[tuple[int | None, int | None], CoverageCell] = {}
    totals = CoverageCounts()
    for row in rows:
        key = (row.category_id, row.batch_id)
        cell = grouped.setdefault(key, CoverageCell(category_id=row.category_id, batch_id=row.batch_id))
        setattr(cell, row.status, getattr(cell, row.status) + row.count)
        setattr(totals, row.status, getattr(totals, row.status) + row.count)
        cell.total += row.count
        totals.total += row.count
    return CoverageRead(dataset_id=dataset_id,
        categories=[CoverageAxis(id=row.id, name=row.name) for row in categories] + [CoverageAxis(id=None, name="未分配类别")],
        batches=[CoverageAxis(id=row.id, name=row.name) for row in batches] + [CoverageAxis(id=None, name="未分配批次")],
        cells=list(grouped.values()), totals=totals)


def read_coverage_samples(session: Session, dataset_id: int, *, category_id: int | None,
                          batch_id: int | None, status: CoverageStatus, page: int = 1,
                          page_size: int = 12) -> CoverageSamplesRead:
    dataset = get_dataset_or_404(session, dataset_id)
    for identity, model in ((category_id, DatasetCategory), (batch_id, DatasetBatch)):
        if identity is not None:
            entity = session.get(model, identity)
            if entity is None or entity.dataset_id != dataset_id:
                raise HTTPException(422, "类别或批次不属于当前数据集。")
    scope = [Sample.dataset_id == dataset_id, Sample.file_type == "image",
        Sample.category_id == category_id if category_id is not None else Sample.category_id.is_(None),
        Sample.batch_id == batch_id if batch_id is not None else Sample.batch_id.is_(None)]
    if status != "all":
        scope.append(_coverage_status(dataset.triage_policy_version) == status)
    total = int(session.exec(select(func.count(Sample.id)).where(*scope)).one())
    page = min(page, max((total + page_size - 1) // page_size, 1))
    rows = session.exec(select(Sample).where(*scope)
        .order_by(func.lower(Sample.relative_path), Sample.relative_path, Sample.id)
        .offset((page - 1) * page_size).limit(page_size).options(selectinload(Sample.tags))).all()
    return CoverageSamplesRead(items=[to_sample_read(row, dataset.triage_policy_version) for row in rows],
        total=total, page=page, page_size=page_size)
