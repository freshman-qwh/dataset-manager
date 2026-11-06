"""Compare one object category using only current registered metadata."""
from fastapi import HTTPException
from sqlalchemy import and_, case, func
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, select

from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.schemas.comparison import ComparisonRead, ComparisonSide
from app.services.dataset_card_service import effective_image_label
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import to_sample_read


def read_comparison(
    session: Session,
    dataset_id: int,
    *,
    category_id: int | None = None,
    batch_id: int | None = None,
    normal_page: int = 1,
    anomaly_page: int = 1,
    page_size: int = 8,
) -> ComparisonRead:
    dataset = get_dataset_or_404(session, dataset_id)
    if category_id is not None:
        category = session.get(DatasetCategory, category_id)
        if category is None or category.dataset_id != dataset_id:
            raise HTTPException(422, "请选择当前数据集的对象类别。")
    if batch_id is not None:
        batch = session.get(DatasetBatch, batch_id)
        if batch is None or batch.dataset_id != dataset_id:
            raise HTTPException(422, "请选择当前数据集的采集批次。")

    scope = [Sample.dataset_id == dataset_id, Sample.file_type == "image"]
    if batch_id is not None:
        scope.append(Sample.batch_id == batch_id)
    if category_id is None:
        # Pick an actual populated category within this batch. Empty category
        # records do not force an empty comparison, and other objects never mix.
        category_id = session.exec(select(DatasetCategory.id)
            .join(Sample, Sample.category_id == DatasetCategory.id)
            .where(DatasetCategory.dataset_id == dataset_id, *scope)
            .group_by(DatasetCategory.id, DatasetCategory.name)
            .order_by(func.lower(DatasetCategory.name), DatasetCategory.name, DatasetCategory.id)
            .limit(1)).first()
    scope.append(Sample.category_id == category_id if category_id is not None else Sample.category_id.is_(None))
    label = effective_image_label(dataset.triage_policy_version)
    available = Sample.file_status == "normal"
    normal = and_(available, label == "normal")
    anomaly = and_(available, label == "anomaly")
    counts = session.exec(select(func.count(Sample.id),
        func.coalesce(func.sum(case((normal, 1), else_=0)), 0),
        func.coalesce(func.sum(case((anomaly, 1), else_=0)), 0))
        .where(*scope)).one()
    page_size = max(1, min(page_size, 24))

    def side(condition: ColumnElement[bool], total: int, requested_page: int) -> ComparisonSide:
        page = min(max(requested_page, 1), max((total + page_size - 1) // page_size, 1))
        rows = session.exec(select(Sample).where(*scope, condition)
            .order_by(func.lower(Sample.relative_path), Sample.relative_path, Sample.id)
            .offset((page - 1) * page_size).limit(page_size)
            .options(selectinload(Sample.tags))).all()
        return ComparisonSide(items=[to_sample_read(sample, dataset.triage_policy_version) for sample in rows],
            total=total, page=page, page_size=page_size)

    return ComparisonRead(dataset_id=dataset_id, category_id=category_id, batch_id=batch_id,
        normal=side(normal, counts[1], normal_page), anomaly=side(anomaly, counts[2], anomaly_page),
        excluded_count=counts[0] - counts[1] - counts[2])
