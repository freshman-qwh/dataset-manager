"""Summarize registered metadata without scanning or decoding original files."""
from sqlalchemy import String, and_, case, cast, func, literal, or_
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.schemas.dataset_card import (
    DatasetCardCategory, DatasetCardPreview, DatasetCardRead,
    DatasetCardSplits, DatasetCardSummary,
)
from app.services import dataset_service


def effective_image_label(policy_version: int) -> ColumnElement[str]:
    """Prefer current human truth; pending/stale judgments never fall back.

    Legacy untriaged images may carry explicitly imported benchmark truth.
    Unknown images and non-image files have no effective label.
    """
    triage = func.coalesce(Sample.triage_status, "untriaged")
    current = and_(Sample.triaged_file_hash == Sample.file_hash,
                   Sample.triage_policy_version == policy_version)
    classified = triage.in_(("ok", "ng"))
    stale = and_(classified, or_(
        Sample.triaged_file_hash.is_(None), Sample.triaged_file_hash != Sample.file_hash,
        Sample.triage_policy_version.is_(None), Sample.triage_policy_version != policy_version,
    ))
    return case(
        (Sample.file_type != "image", None),
        (or_(triage == "pending", stale), "pending"),
        (and_(triage == "ok", current), "normal"),
        (and_(triage == "ng", current), "anomaly"),
        (and_(triage == "untriaged", Sample.benchmark_label == "normal"), "normal"),
        (and_(triage == "untriaged", Sample.benchmark_label == "anomaly"), "anomaly"),
        else_=None,
    )


def _count(condition: ColumnElement[bool]) -> ColumnElement[int]:
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _previews(session: Session, dataset_id: int, label: ColumnElement[str]) -> list[DatasetCardPreview]:
    available = (Sample.dataset_id == dataset_id, Sample.file_type == "image", Sample.file_status == "normal")
    covers = session.exec(select(func.min(Sample.id))
        .join(DatasetCategory, and_(DatasetCategory.id == Sample.category_id, DatasetCategory.dataset_id == dataset_id))
        .where(*available).group_by(Sample.category_id)
        .order_by(func.min(Sample.id)).limit(16)).all()
    # Read only the small representative set. Empty legacy hashes do not imply
    # that distinct files contain the same bytes.
    selected: list[DatasetCardPreview] = []
    selected_ids: set[int] = set()
    seen_hashes: set[str] = set()

    def add_ids(ids: list[int]) -> None:
        if not ids:
            return
        rows = session.exec(select(Sample.id, Sample.filename, Sample.file_hash,
            DatasetCategory.name, label.label("effective_label"))
            .outerjoin(DatasetCategory, and_(DatasetCategory.id == Sample.category_id, DatasetCategory.dataset_id == dataset_id))
            .where(Sample.dataset_id == dataset_id, Sample.id.in_(ids)).order_by(Sample.id)).all()
        for row in rows:
            if len(selected) == 8:
                break
            if row.id in selected_ids or (row.file_hash and row.file_hash in seen_hashes):
                continue
            selected.append(DatasetCardPreview(sample_id=row.id, filename=row.filename,
                file_hash=row.file_hash, category_name=row.name, label=row.effective_label))
            selected_ids.add(row.id)
            if row.file_hash:
                seen_hashes.add(row.file_hash)

    add_ids(list(covers))
    content_key = case((Sample.file_hash != "", Sample.file_hash),
                       else_=literal("sample:") + cast(Sample.id, String))
    # When there are fewer object categories, include both normal and anomaly
    # examples before filling the remaining positions in deterministic order.
    for wanted in ("normal", "anomaly", None):
        remaining = 8 - len(selected)
        if remaining == 0:
            break
        statement = select(func.min(Sample.id)).where(*available)
        if wanted is not None:
            statement = statement.where(label == wanted)
        if selected_ids:
            statement = statement.where(Sample.id.not_in(selected_ids))
        if seen_hashes:
            statement = statement.where(Sample.file_hash.not_in(seen_hashes))
        ids = session.exec(statement.group_by(content_key)
            .order_by(func.min(Sample.id)).limit(min(remaining, 2) if wanted else remaining)).all()
        add_ids(list(ids))
    return selected


def read_dataset_card(session: Session, dataset_id: int) -> DatasetCardRead:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    label = effective_image_label(dataset.triage_policy_version)
    image = Sample.file_type == "image"
    scope = Sample.dataset_id == dataset_id
    totals = session.exec(select(
        func.count(Sample.id), _count(image),
        _count(label == "normal"), _count(label == "anomaly"), _count(label == "pending"),
        _count(and_(image, label.is_(None))),
        _count(Sample.file_status != "normal"),
        _count(and_(image, Sample.mask_path.is_not(None), Sample.mask_path != "")),
        _count(and_(image, Sample.split == "train")),
        _count(and_(image, Sample.split == "val")),
        _count(and_(image, Sample.split == "test")),
        _count(and_(image, or_(Sample.split.is_(None), Sample.split.not_in(("train", "val", "test"))))),
    ).where(scope)).one()
    category_count = session.exec(select(func.count(DatasetCategory.id)).where(DatasetCategory.dataset_id == dataset_id)).one()
    batch_count = session.exec(select(func.count(DatasetBatch.id)).where(DatasetBatch.dataset_id == dataset_id)).one()
    category_totals = select(Sample.category_id.label("category_id"), func.count(Sample.id).label("sample_count"),
        _count(label == "normal").label("normal_count"), _count(label == "anomaly").label("anomaly_count"))
    grouped = category_totals.where(scope).group_by(Sample.category_id).subquery()
    categories = session.exec(select(DatasetCategory.id, DatasetCategory.name,
        func.coalesce(grouped.c.sample_count, 0).label("sample_count"),
        func.coalesce(grouped.c.normal_count, 0).label("normal_count"),
        func.coalesce(grouped.c.anomaly_count, 0).label("anomaly_count"))
        .outerjoin(grouped, grouped.c.category_id == DatasetCategory.id)
        .where(DatasetCategory.dataset_id == dataset_id)
        .order_by(func.lower(DatasetCategory.name), DatasetCategory.id).limit(12)).all()
    return DatasetCardRead(
        dataset=dataset_service._dataset_read(session, dataset), generated_at=utc_now(),
        summary=DatasetCardSummary(sample_count=totals[0], image_count=totals[1],
            normal_count=totals[2], anomaly_count=totals[3], pending_count=totals[4],
            untriaged_count=totals[5], unavailable_count=totals[6], mask_count=totals[7],
            category_count=category_count, batch_count=batch_count,
            splits=DatasetCardSplits(train=totals[8], val=totals[9], test=totals[10], unassigned=totals[11])),
        categories=[DatasetCardCategory(**row._mapping) for row in categories],
        preview_samples=_previews(session, dataset_id, label),
    )
