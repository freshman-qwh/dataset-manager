"""Metadata-only project, object category and acquisition batch operations."""
from fastapi import HTTPException
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.dataset import Dataset, utc_now
from app.models.organization import DatasetBatch, DatasetCategory, Project
from app.models.sample import Sample
from app.schemas.organization import (
    BatchCreate, BatchRead, BatchUpdate, CategoryCreate, CategoryRead, CategoryUpdate,
    DatasetOrganizationRead, OrganizationAssign, OrganizationAssignRead,
    ProjectCreate, ProjectRead, ProjectUpdate,
)
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.dataset_service import get_dataset_or_404


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "名称或编号已存在，请使用其他名称。") from exc


def get_project(session: Session, project_id: int) -> Project:
    value = session.get(Project, project_id)
    if value is None:
        raise HTTPException(404, "项目不存在。")
    return value


def project_read(session: Session, project: Project) -> ProjectRead:
    count = session.exec(select(func.count(Dataset.id)).where(Dataset.project_id == project.id)).one()
    return ProjectRead(**project.model_dump(), dataset_count=count)


def list_projects(session: Session) -> list[ProjectRead]:
    return [project_read(session, row) for row in session.exec(select(Project).order_by(Project.name, Project.id)).all()]


def create_project(session: Session, payload: ProjectCreate) -> ProjectRead:
    value = Project(**payload.model_dump())
    session.add(value)
    _commit(session)
    session.refresh(value)
    return project_read(session, value)


def update_project(session: Session, project_id: int, payload: ProjectUpdate) -> ProjectRead:
    value = get_project(session, project_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and session.exec(select(Project.id).where(Project.name == updates["name"], Project.id != project_id)).first() is not None:
        raise HTTPException(409, "项目名称已存在。")
    for key, item in updates.items():
        setattr(value, key, item)
    value.updated_at = utc_now()
    if "name" in updates:
        datasets = session.exec(select(Dataset).where(Dataset.project_id == project_id)).all()
        for dataset in datasets:
            dataset.project = value.name
            session.add(dataset)
            bump_dataset_revision(session, dataset.id)
    session.add(value)
    _commit(session)
    session.refresh(value)
    return project_read(session, value)


def delete_project(session: Session, project_id: int) -> None:
    value = get_project(session, project_id)
    if session.exec(select(Dataset.id).where(Dataset.project_id == project_id)).first() is not None:
        raise HTTPException(409, "项目仍有数据集，请先调整数据集归属。")
    session.delete(value)
    _commit(session)


def resolve_project_values(session: Session, values: dict[str, object]) -> dict[str, object]:
    """Keep the old string API working while the stable relation owns identity."""
    result = dict(values)
    if "project_id" in result:
        project_id = result["project_id"]
        project = get_project(session, int(project_id)) if project_id is not None else None
        if "project" in result and result["project"] not in (None, "", project.name if project else None):
            raise HTTPException(422, "项目名称和所选项目不一致。")
        result["project"] = project.name if project else None
    elif "project" in result:
        name = str(result["project"] or "").strip()
        project = session.exec(select(Project).where(Project.name == name)).first() if name else None
        if name and project is None:
            project = Project(name=name)
            session.add(project)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(409, "项目名称已存在，请重新加载项目列表。") from exc
        result["project"] = project.name if project else None
        result["project_id"] = project.id if project else None
    return result


def get_category(session: Session, dataset_id: int, category_id: int) -> DatasetCategory:
    value = session.get(DatasetCategory, category_id)
    if value is None or value.dataset_id != dataset_id:
        raise HTTPException(404, "该类别不属于当前数据集。")
    return value


def get_batch(session: Session, dataset_id: int, batch_id: int) -> DatasetBatch:
    value = session.get(DatasetBatch, batch_id)
    if value is None or value.dataset_id != dataset_id:
        raise HTTPException(404, "该批次不属于当前数据集。")
    return value


def list_categories(session: Session, dataset_id: int) -> list[CategoryRead]:
    get_dataset_or_404(session, dataset_id)
    stats = session.exec(select(
        Sample.category_id, func.count(Sample.id),
        func.sum(case((Sample.triage_status == "ok", 1), ((Sample.triage_status == "untriaged") & (Sample.benchmark_label == "normal"), 1), else_=0)),
        func.sum(case((Sample.triage_status == "ng", 1), ((Sample.triage_status == "untriaged") & (Sample.benchmark_label == "anomaly"), 1), else_=0)),
        func.min(case(((Sample.file_type == "image") & (Sample.file_status == "normal"), Sample.id))),
    ).where(Sample.dataset_id == dataset_id).group_by(Sample.category_id)).all()
    grouped = {row[0]: row[1:] for row in stats}
    cover_ids = [row[4] for row in stats if row[4] is not None]
    hashes = dict(session.exec(select(Sample.id, Sample.file_hash).where(Sample.id.in_(cover_ids))).all()) if cover_ids else {}
    result = []
    for value in session.exec(select(DatasetCategory).where(DatasetCategory.dataset_id == dataset_id).order_by(DatasetCategory.name, DatasetCategory.id)).all():
        count, normal, anomaly, cover = grouped.get(value.id, (0, 0, 0, None))
        result.append(CategoryRead(**value.model_dump(), sample_count=count, normal_count=normal,
            anomaly_count=anomaly, cover_sample_id=cover, cover_file_hash=hashes.get(cover)))
    return result


def create_category(session: Session, dataset_id: int, payload: CategoryCreate) -> CategoryRead:
    get_dataset_or_404(session, dataset_id)
    value = DatasetCategory(dataset_id=dataset_id, **payload.model_dump())
    session.add(value)
    try:
        session.flush()
        bump_dataset_revision(session, dataset_id)
        _commit(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "该数据集已有同名类别。") from exc
    return next(row for row in list_categories(session, dataset_id) if row.id == value.id)


def update_category(session: Session, dataset_id: int, category_id: int, payload: CategoryUpdate) -> CategoryRead:
    get_dataset_or_404(session, dataset_id)
    value = get_category(session, dataset_id, category_id)
    for key, item in payload.model_dump(exclude_unset=True).items():
        setattr(value, key, item)
    session.add(value)
    try:
        session.flush()
        bump_dataset_revision(session, dataset_id)
        _commit(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "该数据集已有同名类别。") from exc
    return next(row for row in list_categories(session, dataset_id) if row.id == value.id)


def delete_category(session: Session, dataset_id: int, category_id: int) -> None:
    get_dataset_or_404(session, dataset_id)
    value = get_category(session, dataset_id, category_id)
    if session.exec(select(Sample.id).where(Sample.dataset_id == dataset_id, Sample.category_id == category_id)).first() is not None:
        raise HTTPException(409, "类别仍有图片，请先调整图片类别。")
    session.delete(value)
    bump_dataset_revision(session, dataset_id)
    _commit(session)


def list_batches(session: Session, dataset_id: int) -> list[BatchRead]:
    get_dataset_or_404(session, dataset_id)
    counts = dict(session.exec(select(Sample.batch_id, func.count(Sample.id)).where(Sample.dataset_id == dataset_id).group_by(Sample.batch_id)).all())
    return [BatchRead(**value.model_dump(), sample_count=counts.get(value.id, 0))
        for value in session.exec(select(DatasetBatch).where(DatasetBatch.dataset_id == dataset_id).order_by(DatasetBatch.id.desc())).all()]


def create_batch(session: Session, dataset_id: int, payload: BatchCreate) -> BatchRead:
    get_dataset_or_404(session, dataset_id)
    value = DatasetBatch(dataset_id=dataset_id, **payload.model_dump())
    session.add(value)
    bump_dataset_revision(session, dataset_id)
    _commit(session)
    session.refresh(value)
    return BatchRead(**value.model_dump())


def update_batch(session: Session, dataset_id: int, batch_id: int, payload: BatchUpdate) -> BatchRead:
    get_dataset_or_404(session, dataset_id)
    value = get_batch(session, dataset_id, batch_id)
    for key, item in payload.model_dump(exclude_unset=True).items():
        setattr(value, key, item)
    session.add(value)
    bump_dataset_revision(session, dataset_id)
    _commit(session)
    return next(row for row in list_batches(session, dataset_id) if row.id == batch_id)


def delete_batch(session: Session, dataset_id: int, batch_id: int) -> None:
    get_dataset_or_404(session, dataset_id)
    value = get_batch(session, dataset_id, batch_id)
    if session.exec(select(Sample.id).where(Sample.dataset_id == dataset_id, Sample.batch_id == batch_id)).first() is not None:
        raise HTTPException(409, "批次仍有图片，请先调整图片批次。")
    session.delete(value)
    bump_dataset_revision(session, dataset_id)
    _commit(session)


def read_organization(session: Session, dataset_id: int) -> DatasetOrganizationRead:
    dataset = get_dataset_or_404(session, dataset_id)
    project = get_project(session, dataset.project_id) if dataset.project_id is not None else None
    return DatasetOrganizationRead(project=project_read(session, project) if project else None,
        categories=list_categories(session, dataset_id), batches=list_batches(session, dataset_id))


def assign_samples(session: Session, dataset_id: int, payload: OrganizationAssign) -> OrganizationAssignRead:
    get_dataset_or_404(session, dataset_id)
    updates = payload.model_dump(exclude_unset=True, exclude={"sample_ids"})
    if not updates:
        raise HTTPException(422, "请选择要修改的类别或批次。")
    if payload.category_id is not None:
        get_category(session, dataset_id, payload.category_id)
    batch = get_batch(session, dataset_id, payload.batch_id) if payload.batch_id is not None else None
    ids = set(payload.sample_ids)
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id, Sample.id.in_(ids))).all()
    if {row.id for row in samples} != ids:
        raise HTTPException(422, "所选图片不完全属于当前数据集。")
    changed = 0
    for sample in samples:
        old = (sample.category_id, sample.batch_id, sample.capture_batch_id)
        if "category_id" in updates:
            sample.category_id = payload.category_id
        if "batch_id" in updates:
            sample.batch_id = payload.batch_id
            sample.capture_batch_id = batch.code if batch else None
        if old != (sample.category_id, sample.batch_id, sample.capture_batch_id):
            sample.updated_at = utc_now()
            session.add(sample)
            changed += 1
    revision = bump_dataset_revision(session, dataset_id) if changed else get_dataset_or_404(session, dataset_id).revision
    _commit(session)
    return OrganizationAssignRead(updated_count=changed, dataset_revision=revision)
