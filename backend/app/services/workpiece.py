"""Inspect workpiece metadata without accessing or modifying source files."""

from collections import Counter, defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.workpiece import WorkpieceIsolationRead, WorkpieceViewsRead
from app.services.anomaly_protocol_service import _components, _eligibility
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import to_sample_read


MAX_DATASET_SAMPLES = 10000


def read_workpiece_views(
    session: Session,
    sample_id: int,
    *,
    page: int = 1,
    page_size: int = 12,
) -> WorkpieceViewsRead:
    anchor = session.get(Sample, sample_id)
    if anchor is None:
        raise HTTPException(404, "图片不存在或已被移除。")
    if anchor.file_type != "image":
        raise HTTPException(422, "工件多视角查看仅支持图片。")
    dataset = get_dataset_or_404(session, anchor.dataset_id)
    # Match the formal protocol's complete, dataset-local isolation graph. Read
    # one extra row to reject oversized datasets without loading them in full.
    samples = list(session.exec(select(Sample).where(
        Sample.dataset_id == anchor.dataset_id,
    ).order_by(Sample.id).limit(MAX_DATASET_SAMPLES + 1)).all())
    if len(samples) > MAX_DATASET_SAMPLES:
        raise HTTPException(422, "工件隔离检查最多支持 10000 个登记文件，与工业协议容量一致；请按独立采集批次拆分数据集。")

    if anchor.capture_group_id:
        views = [sample for sample in samples if sample.file_type == "image"
            and sample.capture_group_id == anchor.capture_group_id
            and (sample.capture_batch_id or "") == (anchor.capture_batch_id or "")]
    else:
        views = [sample for sample in samples if sample.id == anchor.id]
    views.sort(key=lambda sample: (sample.relative_path.casefold(), sample.relative_path, sample.id))
    page = min(page, max((len(views) + page_size - 1) // page_size, 1))
    page_ids = [sample.id for sample in views[(page - 1) * page_size:page * page_size]]
    # Load tags only for the visible page; the graph itself needs no tag data.
    visible = {sample.id: sample for sample in session.exec(select(Sample).where(
        Sample.id.in_(page_ids), Sample.dataset_id == anchor.dataset_id,
    ).options(selectinload(Sample.tags))).all()}

    members = next((group for group in _components(samples).values()
        if any(sample.id == anchor.id for sample in group)), None)
    if members is None:
        raise HTTPException(409, "图片在读取期间被移除，请刷新后重试。")
    reasons: Counter[str] = Counter()
    hash_labels: dict[str, set[int]] = defaultdict(set)
    for sample in members:
        label, reason = _eligibility(sample, dataset.triage_policy_version, False, check_file=False)
        if reason:
            reasons[reason] += 1
        elif label == 1:
            reasons["包含 NG 异常，整组不能用于纯正常训练"] += 1
        if not sample.capture_group_id:
            reasons["缺少工件组，尚未确认独立采集"] += 1
        if label is not None:
            hash_labels[sample.file_hash].add(label)
    conflicts = {digest for digest, labels in hash_labels.items() if len(labels) > 1}
    if conflicts:
        reasons["相同内容的正常/异常判定矛盾"] = sum(sample.file_hash in conflicts for sample in members)

    return WorkpieceViewsRead(
        dataset_id=anchor.dataset_id,
        anchor_sample_id=sample_id,
        capture_group_id=anchor.capture_group_id,
        capture_batch_id=anchor.capture_batch_id,
        dataset_revision=dataset.revision,
        items=[to_sample_read(visible[identity], dataset.triage_policy_version) for identity in page_ids],
        total=len(views), page=page, page_size=page_size,
        isolation=WorkpieceIsolationRead(total=len(members), normal_candidate=not reasons, reasons=dict(reasons)),
    )
