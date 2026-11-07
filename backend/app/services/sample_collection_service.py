"""Transactional, versioned sample references without any source file writes."""
import json

from fastapi import HTTPException
from sqlalchemy import delete, inspect, update
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.dataset import Dataset, utc_now
from app.models.organization import DatasetCategory
from app.models.sample import Sample
from app.models.sample_collection import SampleCollection
from app.schemas.sample_collection import (
    CollectionItemInput, CollectionItemRead, SampleCollectionCreate,
    SampleCollectionRead, SampleCollectionUpdate,
)
from app.services.sample_service import to_sample_read


def _ensure_schema(session: Session) -> None:
    if not inspect(session.get_bind()).has_table("sample_collections"):
        raise HTTPException(503, "收集篮与参考卡需要升级数据库，请先备份并执行离线迁移。")


def _get(session: Session, collection_id: int) -> SampleCollection:
    _ensure_schema(session)
    row = session.get(SampleCollection, collection_id)
    if row is None:
        raise HTTPException(404, "该集合不存在，可能已被删除。")
    return row


def _decode(row: SampleCollection) -> list[dict]:
    try:
        value = json.loads(row.items_json)
        if not isinstance(value, list):
            raise ValueError
        return value
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "集合记录无法读取，请从元数据备份恢复。") from exc


def _read(session: Session, row: SampleCollection) -> SampleCollectionRead:
    stored = _decode(row)
    ids = [item["sample_id"] for item in stored]
    samples = {sample.id: sample for sample in session.exec(select(Sample).where(Sample.id.in_(ids)).options(selectinload(Sample.tags))).all()} if ids else {}
    dataset_ids = {sample.dataset_id for sample in samples.values()}
    policies = {dataset.id: dataset.triage_policy_version for dataset in session.exec(select(Dataset).where(Dataset.id.in_(dataset_ids))).all()} if dataset_ids else {}
    items = []
    for item in stored:
        sample = samples.get(item["sample_id"])
        reason = None
        if sample is None or sample.dataset_id != item["dataset_id"] or sample.dataset_id not in policies:
            reason = "样本记录或所属数据集已删除"
            sample = None
        elif sample.file_hash != item["file_hash"]:
            reason = "源图片已变化，请移除后重新加入并确认"
        elif sample.file_status != "normal":
            reason = "原文件当前不可用"
        elif row.kind == "reference" and sample.category_id != row.category_id:
            reason = "样本已不属于此参考卡的类别"
        items.append(CollectionItemRead(**item, sample=to_sample_read(sample, policies.get(sample.dataset_id)) if sample else None, unavailable_reason=reason))
    return SampleCollectionRead(id=row.id, name=row.name, kind=row.kind, dataset_id=row.dataset_id, category_id=row.category_id, version=row.version, items=items, created_at=row.created_at, updated_at=row.updated_at)


def list_collections(session: Session, kind: str | None = None, dataset_id: int | None = None, category_id: int | None = None) -> list[SampleCollectionRead]:
    _ensure_schema(session)
    query = select(SampleCollection)
    if kind is not None:
        query = query.where(SampleCollection.kind == kind)
    if dataset_id is not None:
        query = query.where(SampleCollection.dataset_id == dataset_id)
    if category_id is not None:
        query = query.where(SampleCollection.category_id == category_id)
    return [_read(session, row) for row in session.exec(query.order_by(SampleCollection.updated_at.desc(), SampleCollection.id.desc())).all()]


def get_collection(session: Session, collection_id: int) -> SampleCollectionRead:
    return _read(session, _get(session, collection_id))


def _items(session: Session, row: SampleCollection, inputs: list[CollectionItemInput], previous: list[dict]) -> str:
    ids = [item.sample_id for item in inputs]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "集合中不能重复加入同一图片。")
    old = {item["sample_id"]: item for item in previous}
    samples = {sample.id: sample for sample in session.exec(select(Sample).where(Sample.id.in_(ids))).all()} if ids else {}
    result = []
    for item in inputs:
        # Preserve the exact original reference on edits; stale/deleted samples
        # can be removed, but editing a caption must never refresh their hash.
        if item.sample_id in old:
            entry = {**old[item.sample_id], "verdict": item.verdict, "note": item.note.strip()}
            if item.file_hash is not None and item.file_hash != entry["file_hash"]:
                raise HTTPException(409, "图片引用已变化，请重新加载集合。")
        else:
            sample = samples.get(item.sample_id)
            if sample is None or sample.file_type != "image" or sample.file_status != "normal":
                raise HTTPException(422, f"图片 {item.sample_id} 不存在或不可用，无法加入集合。")
            if row.kind == "reference" and (sample.dataset_id != row.dataset_id or sample.category_id != row.category_id):
                raise HTTPException(422, "参考图片必须属于所选数据集和类别。")
            if item.file_hash is not None and item.file_hash != sample.file_hash:
                raise HTTPException(409, "源图片已变化，请刷新后重新选择。")
            entry = dict(sample_id=item.sample_id, file_hash=sample.file_hash, dataset_id=sample.dataset_id, filename=sample.filename, relative_path=sample.relative_path, verdict=item.verdict, note=item.note.strip())
        if row.kind == "reference" and entry["verdict"] is None:
            raise HTTPException(422, "参考案例请选择可接受、不可接受或待确认。")
        result.append(entry)
    return json.dumps(result, ensure_ascii=False)


def create_collection(session: Session, payload: SampleCollectionCreate) -> SampleCollectionRead:
    _ensure_schema(session)
    if payload.dataset_id is not None and session.get(Dataset, payload.dataset_id) is None:
        raise HTTPException(404, "参考卡所属数据集不存在。")
    if payload.category_id is not None:
        category = session.get(DatasetCategory, payload.category_id)
        if category is None or category.dataset_id != payload.dataset_id:
            raise HTTPException(422, "类别不属于参考卡的数据集。")
    row = SampleCollection(name=payload.name, kind=payload.kind, dataset_id=payload.dataset_id, category_id=payload.category_id)
    row.items_json = _items(session, row, payload.items, [])
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(session, row)


def update_collection(session: Session, collection_id: int, payload: SampleCollectionUpdate) -> SampleCollectionRead:
    row = _get(session, collection_id)
    if row.version != payload.expected_version:
        raise HTTPException(409, "集合已在其他页面更新，请重新加载后再保存。")
    values = dict(version=row.version + 1, updated_at=utc_now())
    if payload.name is not None:
        values["name"] = payload.name
    if payload.items is not None:
        values["items_json"] = _items(session, row, payload.items, _decode(row))
    result = session.execute(update(SampleCollection).where(SampleCollection.id == collection_id, SampleCollection.version == payload.expected_version).values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "集合已更新，请重新加载后再保存。")
    session.commit()
    session.expire_all()
    return get_collection(session, collection_id)


def delete_collection(session: Session, collection_id: int, expected_version: int) -> None:
    _get(session, collection_id)
    result = session.execute(delete(SampleCollection).where(SampleCollection.id == collection_id, SampleCollection.version == expected_version))
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "集合已更新，请重新加载后再删除。")
    session.commit()
