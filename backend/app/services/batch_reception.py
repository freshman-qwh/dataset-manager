"""Preview and atomically fill batch metadata without rewriting images or judgments."""
import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session, select

from app.models.dataset import Dataset
from app.models.industrial_receipt import IndustrialReceipt
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.schemas.batch_reception import (
    BatchReceptionPreviewRequest, BatchReceptionProfile, BatchReceptionProfileRead,
    BatchReceptionProfileWrite,
)
from app.schemas.industrial import ConfirmationRead, FilenameGroupRule, FrozenPlanRead, PlanConfirmation
from app.services import industrial_plan_service as plans
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.dataset_service import get_dataset_or_404
from app.services.triage_service import _policy_values


MAX_SAMPLES = 10000


def _dataset(session: Session, dataset_id: int) -> Dataset:
    dataset = get_dataset_or_404(session, dataset_id)
    if dataset.workflow_profile != "industrial_anomaly":
        raise HTTPException(422, "批次接收方案适用于工业异常检测数据集。")
    return dataset


def _settings(dataset: Dataset) -> dict:
    try:
        values = json.loads(dataset.industrial_settings_json or "{}")
        if not isinstance(values, dict):
            raise ValueError("not an object")
        return values
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "项目配置无法读取，请从已验证的元数据备份恢复。") from exc


def _profile(dataset: Dataset) -> BatchReceptionProfile:
    settings = _settings(dataset)
    try:
        return BatchReceptionProfile.model_validate(settings.get("batch_reception", {
            "filename_rule": settings.get("filename_group_rule"),
        }))
    except ValidationError as exc:
        raise HTTPException(409, "接收方案无法读取，请重新保存有效方案。") from exc


def _validate_categories(session: Session, dataset_id: int, profile: BatchReceptionProfile) -> None:
    requested = {rule.category_id for rule in profile.category_rules}
    if not requested:
        return
    available = set(session.exec(select(DatasetCategory.id).where(
        DatasetCategory.dataset_id == dataset_id, DatasetCategory.id.in_(requested),
    )).all())
    if requested != available:
        raise HTTPException(422, "类别映射包含已删除或不属于当前数据集的类别。")


def read_profile(session: Session, dataset_id: int) -> BatchReceptionProfileRead:
    dataset = _dataset(session, dataset_id)
    policy = _policy_values(dataset)
    return BatchReceptionProfileRead(saved="batch_reception" in _settings(dataset), dataset_revision=dataset.revision, profile=_profile(dataset),
        context={"policy_version": dataset.triage_policy_version, "split_ok": policy.split_ok,
            "ng_grouping": policy.ng_grouping, "roi": _settings(dataset).get("validation_roi")})


def save_profile(session: Session, dataset_id: int, payload: BatchReceptionProfileWrite) -> BatchReceptionProfileRead:
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    try:
        session.expire_all()
        dataset = _dataset(session, dataset_id)
        if dataset.revision != payload.expected_revision:
            raise HTTPException(409, "项目已变化，请重新加载后再保存接收方案。")
        _validate_categories(session, dataset_id, payload.profile)
        settings = _settings(dataset)
        value = payload.profile.model_dump(mode="json")
        if settings.get("batch_reception") != value:
            settings["batch_reception"] = value
            dataset.industrial_settings_json = json.dumps(settings, ensure_ascii=False)
            session.add(dataset)
            bump_dataset_revision(session, dataset_id)
        session.commit()
        session.expire_all()
        return read_profile(session, dataset_id)
    except Exception:
        session.rollback()
        raise


def _mapped_category(path: str, profile: BatchReceptionProfile) -> int | None:
    parent = str(PurePosixPath(path.replace("\\", "/")).parent)
    matches = [rule for rule in profile.category_rules if rule.directory == "."
        or parent == rule.directory or parent.startswith(rule.directory + "/")]
    return max(matches, key=lambda rule: 0 if rule.directory == "." else len(rule.directory)).category_id if matches else None


def _group(path: str, rule: FilenameGroupRule | None) -> str | None:
    if rule is None:
        return None
    relative = PurePosixPath(path.replace("\\", "/"))
    parts = relative.stem.split(rule.delimiter)
    if len(parts) <= rule.keep_segments or any(not value for value in parts):
        return None
    value = rule.delimiter.join(parts[:rule.keep_segments])
    if rule.include_parent and str(relative.parent) != ".":
        value = f"{relative.parent}/{value}"
    return value if len(value) <= 160 else None


def _source_fingerprint(path_value: str, expected_hash: str) -> tuple[int, int, int] | None:
    try:
        path = Path(path_value)
        before = path.stat()
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        after = path.stat()
        first = (before.st_size, before.st_mtime_ns, before.st_ino)
        second = (after.st_size, after.st_mtime_ns, after.st_ino)
        return second if first == second and digest == expected_hash else None
    except (OSError, ValueError):
        return None


def _source_matches(path_value: str, expected_hash: str) -> bool:
    return _source_fingerprint(path_value, expected_hash) is not None


def _same_source_state(path_value: str, expected: tuple[int, int, int]) -> bool:
    try:
        current = Path(path_value).stat()
        return (current.st_size, current.st_mtime_ns, current.st_ino) == expected
    except (OSError, ValueError):
        return False


def preview(session: Session, dataset_id: int, payload: BatchReceptionPreviewRequest) -> FrozenPlanRead:
    dataset = _dataset(session, dataset_id)
    if dataset.revision != payload.expected_revision:
        raise HTTPException(409, "项目已变化，请重新加载后再预览本批接收。")
    if "batch_reception" not in _settings(dataset):
        raise HTTPException(409, "请先保存接收方案，再预览本批元数据。")
    batch = session.get(DatasetBatch, payload.batch_id)
    if batch is None or batch.dataset_id != dataset_id:
        raise HTTPException(422, "采集批次不存在或不属于当前数据集。")
    profile = _profile(dataset)
    _validate_categories(session, dataset_id, profile)
    samples = list(session.exec(select(Sample).where(Sample.dataset_id == dataset_id,
        Sample.batch_id == batch.id, Sample.file_type == "image")
        .order_by(Sample.relative_path, Sample.id).limit(MAX_SAMPLES + 1)).all())
    if len(samples) > MAX_SAMPLES:
        raise HTTPException(422, "单次接收最多 10000 张图片，请缩小采集批次。")
    if not samples:
        raise HTTPException(422, "本批次没有已登记图片，请先通过添加图片完成扫描。")
    hashes = Counter(session.exec(select(Sample.file_hash).where(
        Sample.dataset_id == dataset_id, Sample.file_type == "image",
        Sample.file_hash.in_({sample.file_hash for sample in samples}),
    )).all())
    rows = []
    conflicts = source_errors = unmatched = 0
    for sample in samples:
        category = _mapped_category(sample.relative_path, profile)
        group = _group(sample.relative_path, profile.filename_rule)
        warnings = []
        errors = []
        if sample.capture_batch_id != batch.code:
            errors.append("批次标识不一致，请先核对类别与批次记录")
        if profile.category_rules and category is None:
            warnings.append("目录未匹配类别规则，保留原类别")
        if profile.filename_rule is not None and group is None:
            warnings.append("文件名未匹配工件规则，保留原工件")
        unmatched += bool(warnings)
        if category is not None and sample.category_id is not None and sample.category_id != category:
            errors.append("已有类别与方案冲突，不覆盖已有值")
        if group is not None and sample.capture_group_id and sample.capture_group_id != group:
            errors.append("已有工件与方案冲突，不覆盖已有值")
        conflicts += bool(errors)
        if sample.file_status != "normal" or not _source_matches(sample.absolute_path, sample.file_hash):
            errors.append("原图不可读取或内容已变化，请重新扫描并复核")
            source_errors += 1
        after_category = sample.category_id if sample.category_id is not None else category
        after_group = sample.capture_group_id or group
        changed = not errors and (sample.category_id != after_category or sample.capture_group_id != after_group)
        rows.append(dict(sample_id=sample.id, relative_path=sample.relative_path,
            source_absolute_path=sample.absolute_path, file_hash=sample.file_hash,
            before_category_id=sample.category_id, category_id=after_category,
            before_group=sample.capture_group_id, capture_group_id=after_group,
            batch_id=sample.batch_id, capture_batch_id=sample.capture_batch_id,
            reason="；".join(errors + warnings) or None, changed=changed))
    updated = sum(row["changed"] for row in rows)
    blocked = bool(conflicts or source_errors)
    blockers = []
    if conflicts:
        blockers.append(f"{conflicts} 张图片的已有元数据或批次与方案冲突，请先核对，不会覆盖已有值。")
    if source_errors:
        blockers.append(f"{source_errors} 张原图不可用或已变化，请重新扫描后再预览。")
    summary = dict(batch_id=batch.id, batch_name=batch.name, image_count=len(samples),
        untriaged_count=sum(sample.triage_status == "untriaged" for sample in samples),
        duplicate_count=sum(bool(sample.file_hash) and hashes[sample.file_hash] > 1 for sample in samples),
        unmatched_count=unmatched, conflict_count=conflicts, source_error_count=source_errors,
        updated_count=updated, blocked=blocked, blockers=blockers,
        notice="仅补充本批图片空的类别和工件信息；人工判定、划分、批次及原文件保持不变。重复内容只提示，不自动合组或删除。")
    try:
        plan = plans.freeze("batch_reception", dataset_id, dataset.revision, rows, summary,
            confirmation=f"确认接收批次元数据 {updated} 张图片", profile=profile.model_dump(mode="json"))
    except OSError as exc:
        raise HTTPException(500, "接收预览无法保存，请检查应用存储空间与权限后重试。") from exc
    return plans.page(plan)


def confirm(session: Session, dataset_id: int, plan_id: str, payload: PlanConfirmation) -> ConfirmationRead:
    session.commit()
    existing = session.get(IndustrialReceipt, plan_id)
    plan = plans.load(session, dataset_id, plan_id, fresh=existing is None)
    if (plan["kind"] != "batch_reception" or plan["plan_hash"] != payload.plan_hash
            or plan["confirmation"] != payload.confirmation):
        raise HTTPException(409, "确认内容与本批接收预览不一致。")
    if existing is None and plan["summary"]["blocked"]:
        raise HTTPException(409, "本批接收存在阻断问题，请处理后重新预览。")
    # Read bytes before taking SQLite's write lock, then check both the current
    # metadata revision and cheap source identity inside the atomic transaction.
    source_states = {}
    if existing is None:
        for row in plan["rows"]:
            state = _source_fingerprint(row["source_absolute_path"], row["file_hash"])
            if state is None:
                raise HTTPException(409, "原图不可读取或内容已变化，请重新扫描并预览。")
            source_states[row["sample_id"]] = state
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    try:
        session.expire_all()
        _dataset(session, dataset_id)
        receipt = session.get(IndustrialReceipt, plan_id)
        plan = plans.load(session, dataset_id, plan_id, fresh=receipt is None)
        if (plan["kind"] != "batch_reception" or plan["plan_hash"] != payload.plan_hash
                or plan["confirmation"] != payload.confirmation):
            raise HTTPException(409, "确认内容与本批接收预览不一致。")
        if receipt is not None:
            if receipt.dataset_id != dataset_id or receipt.kind != "batch_reception" or receipt.plan_hash != payload.plan_hash:
                raise HTTPException(409, "本批接收回执不匹配。")
            return ConfirmationRead.model_validate_json(receipt.result_json)
        if plan["summary"]["blocked"]:
            raise HTTPException(409, "本批接收存在阻断问题，请处理后重新预览。")
        updated = 0
        for row in plan["rows"]:
            sample = session.get(Sample, row["sample_id"])
            if (sample is None or sample.dataset_id != dataset_id or sample.batch_id != row["batch_id"]
                    or sample.capture_batch_id != row["capture_batch_id"] or sample.file_hash != row["file_hash"]
                    or sample.category_id != row["before_category_id"] or sample.capture_group_id != row["before_group"]
                    or sample.absolute_path != row["source_absolute_path"] or sample.file_status != "normal"
                    or row["sample_id"] not in source_states
                    or not _same_source_state(sample.absolute_path, source_states[row["sample_id"]])):
                raise HTTPException(409, "图片、来源或本批元数据已变化，请重新扫描并预览。")
            if row["changed"]:
                sample.category_id = row["category_id"]
                sample.capture_group_id = row["capture_group_id"]
                session.add(sample)
                updated += 1
        revision = bump_dataset_revision(session, dataset_id) if updated else _dataset(session, dataset_id).revision
        result = ConfirmationRead(dataset_revision=revision, updated_count=updated)
        session.add(IndustrialReceipt(plan_id=plan_id, dataset_id=dataset_id, kind="batch_reception",
            plan_hash=payload.plan_hash, result_json=result.model_dump_json()))
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()
