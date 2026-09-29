"""Preview and atomically confirm training splits without touching source files."""

from collections import Counter, defaultdict
from hashlib import sha256
import json
from random import Random

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.sample import Sample
from app.schemas.training_split import (
    TrainingSplitCommitRequest,
    TrainingSplitCommitResult,
    TrainingSplitPreview,
    TrainingSplitRequest,
    TrainingSplitRow,
)
from app.services.dataset_service import get_dataset_or_404
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.split_service import _split_counts

SPLITS = ("train", "val", "test")


def _build(session: Session, dataset_id: int, payload: TrainingSplitRequest) -> tuple[TrainingSplitPreview, dict[int, str | None]]:
    dataset = get_dataset_or_404(session, dataset_id)
    if dataset.task_type not in {"detection", "segmentation"}:
        raise HTTPException(422, "Training split suggestions currently require image annotations.")
    if payload.train_ratio <= 0 or payload.train_ratio + payload.val_ratio + (payload.test_ratio if payload.include_test else 0) <= 0:
        raise HTTPException(422, "train_ratio must be greater than zero.")
    all_samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)).all()
    candidates: list[Sample] = []
    excluded_counts: Counter[str] = Counter()
    for sample in all_samples:
        if sample.file_type != "image":
            continue
        if sample.file_status != "normal":
            excluded_counts["unavailable"] += 1
        elif sample.review_status == "rejected":
            excluded_counts["rejected"] += 1
        elif sample.annotation_progress not in {"completed_with_objects", "completed_empty"}:
            excluded_counts["unfinished"] += 1
        elif sample.annotation_progress == "completed_empty" and not payload.include_empty:
            excluded_counts["empty_disabled"] += 1
        elif payload.triage_filter != "all" and sample.triage_status != payload.triage_filter:
            excluded_counts["triage_mismatch"] += 1
        elif payload.triage_filter != "all" and (
            sample.triaged_file_hash != sample.file_hash
            or sample.triage_policy_version != dataset.triage_policy_version
        ):
            excluded_counts["triage_outdated"] += 1
        else:
            candidates.append(sample)
    candidate_ids = {sample.id for sample in candidates}
    if set(payload.overrides) - candidate_ids:
        raise HTTPException(422, "An override refers to a sample outside the candidate set.")
    if not payload.include_test and "test" in payload.overrides.values():
        raise HTTPException(422, "Enable test before assigning samples to the test split.")
    fingerprint_data = [
        (sample.id, sample.split, sample.file_hash, sample.file_status, sample.annotation_progress,
         sample.review_status, sample.triage_status, sample.triaged_file_hash, sample.triage_policy_version,
         sample.updated_at.isoformat())
        for sample in all_samples
    ]
    options = payload.model_dump(mode="json", exclude={"page", "page_size", "fingerprint"})
    fingerprint = sha256(json.dumps([dataset.revision, fingerprint_data, options], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    groups: dict[str, list[Sample]] = defaultdict(list)
    for sample in all_samples:
        if sample.file_hash:
            groups[sample.file_hash].append(sample)
    candidate_groups: dict[str, list[Sample]] = defaultdict(list)
    for sample in candidates:
        candidate_groups[sample.file_hash or f"sample:{sample.id}"].append(sample)
    ratios = {"train": payload.train_ratio, "val": payload.val_ratio, "test": payload.test_ratio if payload.include_test else 0}
    total = sum(ratios.values())
    targets = _split_counts(len(candidates), {name: value / total for name, value in ratios.items()}, payload.include_test)
    assignments: dict[int, str | None] = {}
    warnings: list[str] = []
    blocked = False
    missing_hash_count = sum(not sample.file_hash for sample in candidates)
    if missing_hash_count:
        blocked = True
        warnings.append(f"{missing_hash_count} 张候选图片缺少文件 hash，重新扫描后才能检查重复。")
    for group in candidate_groups.values():
        existing = {sample.split for sample in group if sample.split in SPLITS}
        outside = {sample.split for sample in groups.get(group[0].file_hash, []) if sample.id not in candidate_ids and sample.split in SPLITS}
        explicit = {payload.overrides[sample.id] for sample in group if sample.id in payload.overrides}
        if len(explicit) > 1:
            blocked = True
            warnings.append(f"重复组 {group[0].relative_path} 的人工调整不一致。")
        chosen = next(iter(explicit)) if explicit else next(iter(existing), next(iter(outside), None))
        if len(existing | outside) > 1 and not explicit:
            blocked = True
            warnings.append(f"重复组 {group[0].relative_path} 已跨训练划分，请人工统一。")
        if chosen is not None and outside and chosen not in outside:
            blocked = True
            warnings.append(f"重复组 {group[0].relative_path} 与本次范围外的划分冲突。")
        if chosen is not None and len(outside) > 1:
            blocked = True
            warnings.append(f"重复组 {group[0].relative_path} 的范围外成员已跨划分。")
        if chosen is not None or explicit:
            for sample in group:
                assignments[sample.id] = chosen
    counts = Counter(value for value in assignments.values() if value)
    pending_groups = [group for group in candidate_groups.values() if group[0].id not in assignments]
    Random(payload.seed).shuffle(pending_groups)
    pending_groups.sort(key=lambda group: -len(group))
    active = [name for name in SPLITS if ratios[name] > 0]
    for group in pending_groups:
        chosen = max(active, key=lambda name: (targets[name] - counts[name], -active.index(name)))
        for sample in group:
            assignments[sample.id] = chosen
        counts[chosen] += len(group)
    included = [sample for sample in candidates if assignments[sample.id] is not None]
    split_counts = {name: sum(assignments[sample.id] == name for sample in included) for name in SPLITS}
    if not included:
        blocked = True
        warnings.append("当前条件下没有可纳入训练的图片。")
    if any(split_counts[name] != targets[name] for name in SPLITS):
        warnings.append("既有划分或不可拆分的重复组使实际比例偏离目标。")
    rows = []
    for sample in candidates:
        group = groups.get(sample.file_hash, []) if sample.file_hash else []
        rows.append(TrainingSplitRow(
            sample_id=sample.id, relative_path=sample.relative_path,
            annotation_progress=sample.annotation_progress, triage_status=sample.triage_status,
            current_split=sample.split, suggested_split=assignments[sample.id],
            duplicate_count=len(group),
            warning="重复图片：需与同组保持相同划分" if len(group) > 1 else None,
        ))
    page_count = max((len(rows) + payload.page_size - 1) // payload.page_size, 1)
    page = min(payload.page, page_count)
    preview = TrainingSplitPreview(
        dataset_id=dataset_id, fingerprint=fingerprint, candidate_count=len(candidates),
        unassigned_count=sum(sample.split not in SPLITS for sample in candidates),
        duplicate_group_count=sum(
            bool(group[0].file_hash) and len(groups[group[0].file_hash]) > 1
            for group in candidate_groups.values()
        ),
        excluded_counts=dict(excluded_counts),
        change_count=sum(assignments[sample.id] != sample.split for sample in included),
        split_counts=split_counts, blocked=blocked, warnings=warnings[:50],
        page=page, page_count=page_count,
        rows=rows[(page - 1) * payload.page_size:page * payload.page_size],
    )
    return preview, assignments


def preview_training_split(session: Session, dataset_id: int, payload: TrainingSplitRequest) -> TrainingSplitPreview:
    return _build(session, dataset_id, payload)[0]


def commit_training_split(session: Session, dataset_id: int, payload: TrainingSplitCommitRequest) -> TrainingSplitCommitResult:
    preview, assignments = _build(session, dataset_id, payload)
    if preview.fingerprint != payload.fingerprint:
        raise HTTPException(409, "Training data changed; preview the split again.")
    if preview.blocked:
        raise HTTPException(422, "Resolve split conflicts before confirming.")
    changed = 0
    for sample in session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all():
        if sample.id in assignments and assignments[sample.id] is not None and assignments[sample.id] != sample.split:
            sample.split = assignments[sample.id]
            sample.updated_at = utc_now()
            session.add(sample)
            changed += 1
    if changed:
        bump_dataset_revision(session, dataset_id)
    session.commit()
    return TrainingSplitCommitResult(
        updated=changed,
        sample_ids=sorted(sample_id for sample_id, split in assignments.items() if split is not None),
        split_counts=preview.split_counts,
        dataset_revision=get_dataset_or_404(session, dataset_id).revision,
    )
