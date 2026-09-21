from __future__ import annotations

import hashlib
import json
import re
from datetime import timezone
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import String, case, cast, delete, exists, func, inspect, insert, literal, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.dataset import Dataset, utc_now
from app.models.defect_type import DefectType, SampleDefectLink
from app.models.sample import Sample
from app.schemas.triage import (
    BatchTriageCommitRequest,
    BatchTriageCommitResponse,
    BatchTriageExpectedSample,
    BatchTriageOperation,
    BatchTriagePreviewItem,
    BatchTriagePreviewRequest,
    BatchTriagePreviewResponse,
    BatchTriageState,
    DefectTypeCreate,
    DefectTypeRead,
    DefectTypeUpdate,
    SampleTriageRead,
    SampleTriageWrite,
    TriageNavigationResponse,
    TriagePolicyImpactPreview,
    TriagePolicyPreviewRequest,
    TriagePolicyRead,
    TriagePolicyUpdateRequest,
    TriagePolicyValues,
    TriageQueueScope,
    TriageStats,
)
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import get_sample_or_404, to_sample_read


class TriageError(RuntimeError):
    pass


class TriageSchemaUnavailableError(TriageError):
    pass


class TriageConflictError(TriageError):
    pass


class TriageValidationError(TriageError):
    pass


class TriageNotFoundError(TriageError):
    pass


def _ensure_schema(session: Session) -> None:
    inspector = inspect(session.get_bind())
    tables = set(inspector.get_table_names())
    if not {"defect_types", "sample_defect_links"}.issubset(tables):
        raise TriageSchemaUnavailableError(
            "快速分拣数据结构尚未启用，请先停止服务并运行数据库迁移。"
        )
    sample_columns = {item["name"] for item in inspector.get_columns("samples")}
    if "triage_status" not in sample_columns:
        raise TriageSchemaUnavailableError(
            "快速分拣数据结构尚未启用，请先停止服务并运行数据库迁移。"
        )
    dataset_columns = {item["name"] for item in inspector.get_columns("datasets")}
    if "triage_onboarding_completed" not in dataset_columns:
        raise TriageSchemaUnavailableError(
            "快速分拣首次配置数据结构尚未启用，请先停止服务并运行数据库迁移。"
        )


def _defect_type_read(item: DefectType) -> DefectTypeRead:
    return DefectTypeRead(
        id=item.id or 0,
        dataset_id=item.dataset_id,
        name=item.name,
        code=item.code,
        parent_id=item.parent_id,
        description=item.description,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _default_policy() -> TriagePolicyValues:
    return TriagePolicyValues()


def _policy_values(dataset: Dataset) -> TriagePolicyValues:
    if not dataset.triage_policy_json:
        return _default_policy()
    try:
        return TriagePolicyValues.model_validate_json(dataset.triage_policy_json)
    except (ValueError, TypeError):
        return _default_policy()


def configured_export_bucket(
    policy: TriagePolicyValues,
    *,
    triage_status: str,
    ok_grade: str | None,
    defect_severity: str | None,
    defect_types: list[DefectType],
    primary_defect_type_id: int | None,
) -> str | None:
    """Return the canonical relative export directory for one triage result."""
    if triage_status == "ok":
        if not policy.split_ok:
            return "ok"
        return f"ok/{ok_grade or 'ungraded'}"
    if triage_status != "ng":
        return None

    selected = list(defect_types)
    primary = next(
        (item for item in selected if item.id == primary_defect_type_id),
        None,
    )
    if primary is not None:
        defect_bucket = primary.code
    elif len(selected) == 1:
        defect_bucket = selected[0].code
    elif len(selected) > 1:
        defect_bucket = "multi_defect"
    else:
        defect_bucket = "unknown"
    severity_bucket = defect_severity or "ungraded"

    if policy.ng_grouping == "none":
        return "ng"
    if policy.ng_grouping == "defect_type":
        return f"ng/{defect_bucket}"
    if policy.ng_grouping == "severity":
        return f"ng/{severity_bucket}"
    return f"ng/{defect_bucket}/{severity_bucket}"


def validate_triage_filters(
    session: Session,
    dataset_id: int,
    *,
    ok_grade: str | None = None,
    defect_severity: str | None = None,
    defect_type_id: int | None = None,
) -> None:
    dataset = get_dataset_or_404(session, dataset_id)
    policy = _policy_values(dataset)
    if ok_grade is not None and not policy.split_ok:
        raise TriageValidationError("当前分拣层级未细分 OK，不能按 OK 等级筛选。")
    if defect_type_id is not None and policy.ng_grouping not in {
        "defect_type",
        "defect_type_and_severity",
    }:
        raise TriageValidationError("当前 NG 分拣层级未启用缺陷类别筛选。")
    if defect_severity is not None and policy.ng_grouping not in {
        "severity",
        "defect_type_and_severity",
    }:
        raise TriageValidationError("当前 NG 分拣层级未启用缺陷程度筛选。")


def _validate_triage_payload(
    policy: TriagePolicyValues,
    payload: SampleTriageWrite,
) -> None:
    has_defect_types = bool(payload.defect_type_ids or payload.primary_defect_type_id)
    if payload.triage_status == "ok":
        if policy.split_ok and payload.ok_grade is None:
            raise TriageValidationError("当前分拣层级要求 OK 选择“完全”或“勉强”。")
        if not policy.split_ok and payload.ok_grade is not None:
            raise TriageValidationError("当前分拣层级使用统一 OK，不能提交 OK 等级。")
        if not policy.split_ok and (has_defect_types or payload.defect_severity is not None):
            raise TriageValidationError("统一 OK 不记录缺陷类别或程度。")
        return
    if payload.triage_status != "ng":
        return

    allows_type = policy.ng_grouping in {"defect_type", "defect_type_and_severity"}
    allows_severity = policy.ng_grouping in {"severity", "defect_type_and_severity"}
    if has_defect_types and not allows_type:
        raise TriageValidationError("当前 NG 分拣层级未启用缺陷类别。")
    if payload.defect_severity is not None and not allows_severity:
        raise TriageValidationError("当前 NG 分拣层级未启用缺陷程度。")


def get_triage_policy(session: Session, dataset_id: int) -> TriagePolicyRead:
    _ensure_schema(session)
    dataset = get_dataset_or_404(session, dataset_id)
    return TriagePolicyRead(
        dataset_id=dataset_id,
        version=dataset.triage_policy_version,
        onboarding_completed=dataset.triage_onboarding_completed,
        **_policy_values(dataset).model_dump(),
    )


def _policy_from_request(payload: TriagePolicyPreviewRequest) -> TriagePolicyValues:
    return TriagePolicyValues.model_validate(
        payload.model_dump(exclude={"expected_version", "complete_onboarding"})
    )


def preview_triage_policy_change(
    session: Session,
    dataset_id: int,
    payload: TriagePolicyPreviewRequest,
) -> TriagePolicyImpactPreview:
    _ensure_schema(session)
    dataset = get_dataset_or_404(session, dataset_id)
    if dataset.triage_policy_version != payload.expected_version:
        raise TriageConflictError("分拣层级已被其他操作修改，请刷新后重试。")

    current = _policy_values(dataset)
    target = _policy_from_request(payload)
    changed = current != target
    image_filter = (
        Sample.dataset_id == dataset_id,
        Sample.file_type == "image",
    )
    processed_filter = (*image_filter, Sample.triage_status != "untriaged")
    processed_count = int(
        session.exec(select(func.count(Sample.id)).where(*processed_filter)).one()
    )

    removes_ok_grade = current.split_ok and not target.split_ok
    current_uses_type = current.ng_grouping in {"defect_type", "defect_type_and_severity"}
    target_uses_type = target.ng_grouping in {"defect_type", "defect_type_and_severity"}
    current_uses_severity = current.ng_grouping in {"severity", "defect_type_and_severity"}
    target_uses_severity = target.ng_grouping in {"severity", "defect_type_and_severity"}

    retained_sample_ids: set[int] = set()
    if removes_ok_grade:
        retained_sample_ids.update(
            session.exec(
                select(Sample.id).where(
                    *image_filter,
                    Sample.triage_status == "ok",
                    Sample.ok_grade.is_not(None),
                )
            ).all()
        )
    if current_uses_type and not target_uses_type:
        retained_sample_ids.update(
            session.exec(
                select(SampleDefectLink.sample_id)
                .join(Sample, Sample.id == SampleDefectLink.sample_id)
                .where(*image_filter, Sample.triage_status == "ng")
                .distinct()
            ).all()
        )
    if current_uses_severity and not target_uses_severity:
        retained_sample_ids.update(
            session.exec(
                select(Sample.id).where(
                    *image_filter,
                    Sample.triage_status == "ng",
                    Sample.defect_severity.is_not(None),
                )
            ).all()
        )

    missing_ok_grade_count = 0
    if not current.split_ok and target.split_ok:
        missing_ok_grade_count = int(
            session.exec(
                select(func.count(Sample.id)).where(
                    *image_filter,
                    Sample.triage_status == "ok",
                    Sample.ok_grade.is_(None),
                )
            ).one()
        )
    missing_defect_type_count = 0
    if not current_uses_type and target_uses_type:
        missing_defect_type_count = int(
            session.exec(
                select(func.count(Sample.id)).where(
                    *image_filter,
                    Sample.triage_status == "ng",
                    ~exists().where(SampleDefectLink.sample_id == Sample.id),
                )
            ).one()
        )
    missing_severity_count = 0
    if not current_uses_severity and target_uses_severity:
        missing_severity_count = int(
            session.exec(
                select(func.count(Sample.id)).where(
                    *image_filter,
                    Sample.triage_status == "ng",
                    Sample.defect_severity.is_(None),
                )
            ).one()
        )

    warnings: list[str] = []
    if changed and processed_count:
        warnings.append(f"已有 {processed_count} 张图片完成过判定，修改后会标记为待复核。")
    if retained_sample_ids:
        warnings.append(
            f"其中 {len(retained_sample_ids)} 张的细分信息会保留在数据库中，但不再参与当前目录结构；重新保存后会按新规则清理。"
        )
    missing_total = (
        missing_ok_grade_count + missing_defect_type_count + missing_severity_count
    )
    if missing_total:
        warnings.append("启用更细层级后，旧判定缺少的新字段需要人工补充。")

    return TriagePolicyImpactPreview(
        dataset_id=dataset_id,
        current_version=dataset.triage_policy_version,
        changed=changed,
        processed_count=processed_count,
        requires_review_count=processed_count if changed else 0,
        retained_detail_count=len(retained_sample_ids),
        missing_ok_grade_count=missing_ok_grade_count,
        missing_defect_type_count=missing_defect_type_count,
        missing_severity_count=missing_severity_count,
        warnings=warnings,
    )


def update_triage_policy(
    session: Session,
    dataset_id: int,
    payload: TriagePolicyUpdateRequest,
) -> TriagePolicyRead:
    _ensure_schema(session)
    dataset = get_dataset_or_404(session, dataset_id)
    if dataset.triage_policy_version != payload.expected_version:
        raise TriageConflictError("分拣层级已被其他操作修改，请刷新后重试。")
    current = _policy_values(dataset)
    target = _policy_from_request(payload)
    if current == target:
        if payload.complete_onboarding and not dataset.triage_onboarding_completed:
            dataset.triage_onboarding_completed = True
            session.add(dataset)
            bump_dataset_revision(session, dataset_id)
            session.commit()
        return get_triage_policy(session, dataset_id)
    dataset.triage_policy_json = json.dumps(
        target.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    dataset.triage_policy_version += 1
    if payload.complete_onboarding:
        dataset.triage_onboarding_completed = True
    session.add(dataset)
    bump_dataset_revision(session, dataset_id)
    session.commit()
    session.refresh(dataset)
    return get_triage_policy(session, dataset_id)


def _normalized_code(value: str | None) -> str:
    if value:
        code = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
        if code:
            return code[:80]
    return f"defect-{uuid4().hex[:10]}"


def _validate_parent(
    session: Session,
    dataset_id: int,
    parent_id: int | None,
    *,
    current_id: int | None = None,
) -> DefectType | None:
    if parent_id is None:
        return None
    if current_id is not None and parent_id == current_id:
        raise TriageValidationError("缺陷类型不能以自身作为父类型。")
    parent = session.get(DefectType, parent_id)
    if parent is None or parent.dataset_id != dataset_id:
        raise TriageValidationError("父缺陷类型不属于当前数据集。")
    if not parent.is_active:
        raise TriageValidationError("不能在已停用的缺陷类型下新增或移动子类型。")
    if parent.parent_id is not None:
        raise TriageValidationError("缺陷类型最多支持两级。")
    return parent


def list_defect_types(
    session: Session,
    dataset_id: int,
    *,
    include_inactive: bool = True,
) -> list[DefectTypeRead]:
    _ensure_schema(session)
    get_dataset_or_404(session, dataset_id)
    statement = select(DefectType).where(DefectType.dataset_id == dataset_id)
    if not include_inactive:
        statement = statement.where(DefectType.is_active.is_(True))
    items = session.exec(statement.order_by(DefectType.parent_id, DefectType.name, DefectType.id)).all()
    return [_defect_type_read(item) for item in items]


def create_defect_type(
    session: Session,
    dataset_id: int,
    payload: DefectTypeCreate,
) -> DefectTypeRead:
    _ensure_schema(session)
    get_dataset_or_404(session, dataset_id)
    _validate_parent(session, dataset_id, payload.parent_id)
    duplicate_name = session.exec(
        select(DefectType.id).where(
            DefectType.dataset_id == dataset_id,
            func.lower(DefectType.name) == payload.name.casefold(),
        )
    ).first()
    if duplicate_name is not None:
        raise TriageConflictError(f'缺陷类型“{payload.name}”已存在。')
    item = DefectType(
        dataset_id=dataset_id,
        name=payload.name,
        code=_normalized_code(payload.code or payload.name),
        parent_id=payload.parent_id,
        description=payload.description,
    )
    session.add(item)
    try:
        session.flush()
        bump_dataset_revision(session, dataset_id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise TriageConflictError("缺陷类型名称或目录代码已存在。") from exc
    session.refresh(item)
    return _defect_type_read(item)


def update_defect_type(
    session: Session,
    dataset_id: int,
    defect_type_id: int,
    payload: DefectTypeUpdate,
) -> DefectTypeRead:
    _ensure_schema(session)
    get_dataset_or_404(session, dataset_id)
    item = session.get(DefectType, defect_type_id)
    if item is None or item.dataset_id != dataset_id:
        raise TriageNotFoundError("缺陷类型不存在。")
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        duplicate_name = session.exec(
            select(DefectType.id).where(
                DefectType.dataset_id == dataset_id,
                DefectType.id != defect_type_id,
                func.lower(DefectType.name) == updates["name"].casefold(),
            )
        ).first()
        if duplicate_name is not None:
            raise TriageConflictError(f'缺陷类型“{updates["name"]}”已存在。')
    if "parent_id" in updates:
        _validate_parent(
            session,
            dataset_id,
            updates["parent_id"],
            current_id=defect_type_id,
        )
        children_exist = session.exec(
            select(DefectType.id).where(DefectType.parent_id == defect_type_id).limit(1)
        ).first()
        if children_exist is not None and updates["parent_id"] is not None:
            raise TriageValidationError("已有子类型的缺陷类型不能再改为二级类型。")
    changed = False
    for key, value in updates.items():
        normalized = _normalized_code(value) if key == "code" else value
        if getattr(item, key) != normalized:
            setattr(item, key, normalized)
            changed = True
    if not changed:
        return _defect_type_read(item)
    item.updated_at = utc_now().astimezone(timezone.utc)
    session.add(item)
    try:
        bump_dataset_revision(session, dataset_id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise TriageConflictError("缺陷类型名称或目录代码已存在。") from exc
    session.refresh(item)
    return _defect_type_read(item)


def _selected_defect_types(session: Session, sample_id: int) -> list[DefectType]:
    return list(
        session.exec(
            select(DefectType)
            .join(SampleDefectLink, SampleDefectLink.defect_type_id == DefectType.id)
            .where(SampleDefectLink.sample_id == sample_id)
            .order_by(DefectType.parent_id, DefectType.name, DefectType.id)
        ).all()
    )


def defect_types_by_sample(
    session: Session,
    sample_ids: list[int],
) -> dict[int, list[DefectType]]:
    if not sample_ids:
        return {}
    rows = session.exec(
        select(SampleDefectLink.sample_id, DefectType)
        .join(DefectType, DefectType.id == SampleDefectLink.defect_type_id)
        .where(SampleDefectLink.sample_id.in_(sample_ids))
        .order_by(SampleDefectLink.sample_id, DefectType.parent_id, DefectType.name)
    ).all()
    result: dict[int, list[DefectType]] = {}
    for sample_id, defect_type in rows:
        result.setdefault(int(sample_id), []).append(defect_type)
    return result


def get_sample_triage(session: Session, sample_id: int) -> SampleTriageRead:
    _ensure_schema(session)
    sample = get_sample_or_404(session, sample_id)
    dataset = get_dataset_or_404(session, sample.dataset_id)
    defect_types = _selected_defect_types(session, sample_id)
    outdated = sample.triage_status != "untriaged" and (
        sample.triaged_file_hash != sample.file_hash
        or sample.triage_policy_version != dataset.triage_policy_version
    )
    return SampleTriageRead(
        sample_id=sample.id or 0,
        dataset_id=sample.dataset_id,
        file_hash=sample.file_hash,
        triage_status=sample.triage_status,
        ok_grade=sample.ok_grade,
        defect_severity=sample.defect_severity,
        defect_types=[_defect_type_read(item) for item in defect_types],
        primary_defect_type_id=sample.primary_defect_type_id,
        triage_note=sample.triage_note,
        triage_version=sample.triage_version,
        triaged_at=sample.triaged_at,
        triage_policy_version=sample.triage_policy_version,
        current_policy_version=dataset.triage_policy_version,
        outdated=outdated,
    )


def replace_sample_triage(
    session: Session,
    sample_id: int,
    payload: SampleTriageWrite,
) -> SampleTriageRead:
    _ensure_schema(session)
    sample = get_sample_or_404(session, sample_id)
    if sample.file_type != "image":
        raise TriageValidationError("快速分拣只支持图片样本。")
    dataset = get_dataset_or_404(session, sample.dataset_id)
    _validate_triage_payload(_policy_values(dataset), payload)
    if sample.triage_version != payload.expected_version:
        raise TriageConflictError("分拣结果已被修改，请刷新后重试。")
    if sample.file_hash != payload.expected_file_hash:
        raise TriageConflictError("样本内容已变化，请查看最新图片后重新判定。")

    selected: list[DefectType] = []
    if payload.defect_type_ids:
        selected = list(
            session.exec(
                select(DefectType).where(DefectType.id.in_(payload.defect_type_ids))
            ).all()
        )
        if len(selected) != len(payload.defect_type_ids) or any(
            item.dataset_id != sample.dataset_id or not item.is_active for item in selected
        ):
            raise TriageValidationError("所选缺陷类型不存在、已停用或不属于当前数据集。")

    current_ids = sorted(item.id or 0 for item in _selected_defect_types(session, sample_id))
    unchanged = (
        sample.triage_status == payload.triage_status
        and sample.ok_grade == payload.ok_grade
        and sample.defect_severity == payload.defect_severity
        and sample.primary_defect_type_id == payload.primary_defect_type_id
        and sample.triage_note == payload.triage_note
        and current_ids == payload.defect_type_ids
        and (
            payload.triage_status == "untriaged"
            or (
                sample.triaged_file_hash == sample.file_hash
                and sample.triage_policy_version == dataset.triage_policy_version
            )
        )
    )
    if unchanged:
        return get_sample_triage(session, sample_id)

    now = utc_now().astimezone(timezone.utc)
    is_reset = payload.triage_status == "untriaged"
    result = session.connection().execute(
        update(Sample)
        .where(
            Sample.id == sample_id,
            Sample.triage_version == payload.expected_version,
            Sample.file_hash == payload.expected_file_hash,
        )
        .values(
            triage_status=payload.triage_status,
            ok_grade=payload.ok_grade,
            defect_severity=payload.defect_severity,
            primary_defect_type_id=payload.primary_defect_type_id,
            triage_note=payload.triage_note,
            triage_version=Sample.triage_version + 1,
            triaged_at=None if is_reset else now,
            triage_policy_version=None if is_reset else dataset.triage_policy_version,
            triaged_file_hash=None if is_reset else sample.file_hash,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise TriageConflictError("分拣结果已被修改，请刷新后重试。")
    session.connection().execute(
        delete(SampleDefectLink).where(SampleDefectLink.sample_id == sample_id)
    )
    for defect_type_id in payload.defect_type_ids:
        session.add(
            SampleDefectLink(sample_id=sample_id, defect_type_id=defect_type_id)
        )
    bump_dataset_revision(session, sample.dataset_id)
    session.commit()
    return get_sample_triage(session, sample_id)


def _batch_state(
    sample: Sample,
    defect_type_ids: list[int],
    *,
    current_policy_version: int,
) -> BatchTriageState:
    outdated = sample.triage_status != "untriaged" and (
        sample.triaged_file_hash != sample.file_hash
        or sample.triage_policy_version != current_policy_version
    )
    return BatchTriageState(
        triage_status=sample.triage_status,
        ok_grade=sample.ok_grade,
        defect_severity=sample.defect_severity,
        defect_type_ids=defect_type_ids,
        primary_defect_type_id=sample.primary_defect_type_id,
        triage_note=sample.triage_note,
        triage_version=sample.triage_version,
        outdated=outdated,
    )


def _batch_value(mode: str, current: object, value: object) -> object:
    if mode == "set":
        return value
    if mode == "clear":
        return None
    return current


def _batch_payload(
    sample: Sample,
    current_defect_type_ids: list[int],
    operation: BatchTriageOperation,
) -> SampleTriageWrite:
    triage_status = _batch_value(
        operation.triage_status_mode,
        sample.triage_status,
        operation.triage_status,
    )
    if triage_status is None or triage_status == "untriaged":
        return SampleTriageWrite(
            expected_version=sample.triage_version,
            expected_file_hash=sample.file_hash,
            triage_status="untriaged",
        )

    if operation.defect_types_mode == "append":
        defect_type_ids = sorted(
            set(current_defect_type_ids) | set(operation.defect_type_ids)
        )
    elif operation.defect_types_mode == "replace":
        defect_type_ids = operation.defect_type_ids
    elif operation.defect_types_mode == "clear":
        defect_type_ids = []
    else:
        defect_type_ids = current_defect_type_ids

    return SampleTriageWrite(
        expected_version=sample.triage_version,
        expected_file_hash=sample.file_hash,
        triage_status=triage_status,
        ok_grade=_batch_value(
            operation.ok_grade_mode,
            sample.ok_grade,
            operation.ok_grade,
        ),
        defect_severity=_batch_value(
            operation.defect_severity_mode,
            sample.defect_severity,
            operation.defect_severity,
        ),
        defect_type_ids=defect_type_ids,
        primary_defect_type_id=_batch_value(
            operation.primary_defect_type_mode,
            sample.primary_defect_type_id,
            operation.primary_defect_type_id,
        ),
        triage_note=_batch_value(
            operation.triage_note_mode,
            sample.triage_note,
            operation.triage_note,
        ),
    )


def _batch_payload_is_unchanged(
    sample: Sample,
    current_defect_type_ids: list[int],
    payload: SampleTriageWrite,
    *,
    current_policy_version: int,
) -> bool:
    return (
        sample.triage_status == payload.triage_status
        and sample.ok_grade == payload.ok_grade
        and sample.defect_severity == payload.defect_severity
        and sample.primary_defect_type_id == payload.primary_defect_type_id
        and sample.triage_note == payload.triage_note
        and current_defect_type_ids == payload.defect_type_ids
        and (
            payload.triage_status == "untriaged"
            or (
                sample.triaged_file_hash == sample.file_hash
                and sample.triage_policy_version == current_policy_version
            )
        )
    )


def _batch_validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc)
    message = str(errors[0].get("msg") or "批量分拣结果不合法。")
    message = message.removeprefix("Value error, ")
    translations = {
        "Only OK samples may have an ok_grade": "只有 OK 样本可以保留 OK 等级。",
        "Clear OK samples cannot have defect types or severity": "完全 OK 不能保留缺陷类型或程度。",
        "Untriaged samples cannot retain triage details": "清空判定时不能保留其他分拣详情。",
        "primary_defect_type_id must be selected in defect_type_ids": "主要缺陷必须包含在已选缺陷类型中。",
    }
    return translations.get(message, message)


def _load_batch_samples(
    session: Session,
    dataset_id: int,
    sample_ids: list[int],
) -> list[Sample]:
    samples = list(
        session.exec(
            select(Sample).where(
                Sample.dataset_id == dataset_id,
                Sample.id.in_(sample_ids),
            )
        ).all()
    )
    by_id = {sample.id: sample for sample in samples}
    missing = [sample_id for sample_id in sample_ids if sample_id not in by_id]
    if missing:
        raise TriageValidationError(
            f"有 {len(missing)} 个样本不存在或不属于当前数据集，请刷新选择后重试。"
        )
    ordered = [by_id[sample_id] for sample_id in sample_ids]
    if any(sample.file_type != "image" for sample in ordered):
        raise TriageValidationError("批量分拣只支持图片样本，请移除其他类型后重试。")
    return ordered


def _dataset_defect_types(session: Session, dataset_id: int) -> dict[int, DefectType]:
    return {
        item.id or 0: item
        for item in session.exec(
            select(DefectType).where(DefectType.dataset_id == dataset_id)
        ).all()
    }


def _validate_batch_payload(
    policy: TriagePolicyValues,
    payload: SampleTriageWrite,
    defect_types: dict[int, DefectType],
) -> None:
    _validate_triage_payload(policy, payload)
    selected = [defect_types.get(item) for item in payload.defect_type_ids]
    if any(item is None or not item.is_active for item in selected):
        raise TriageValidationError("所选缺陷类型不存在、已停用或不属于当前数据集。")


def _validate_operation_references(
    operation: BatchTriageOperation,
    defect_types: dict[int, DefectType],
) -> None:
    referenced_ids = set(operation.defect_type_ids)
    if operation.primary_defect_type_id is not None:
        referenced_ids.add(operation.primary_defect_type_id)
    if any(
        item_id not in defect_types or not defect_types[item_id].is_active
        for item_id in referenced_ids
    ):
        raise TriageValidationError(
            "批量操作引用的缺陷类型不存在、已停用或不属于当前数据集。"
        )


def _batch_preview_hash(
    dataset_id: int,
    policy_version: int,
    operation: BatchTriageOperation,
    expected_samples: list[BatchTriageExpectedSample],
) -> str:
    value = {
        "dataset_id": dataset_id,
        "policy_version": policy_version,
        "operation": operation.model_dump(mode="json"),
        "expected_samples": [item.model_dump(mode="json") for item in expected_samples],
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def preview_batch_triage(
    session: Session,
    dataset_id: int,
    request: BatchTriagePreviewRequest,
) -> BatchTriagePreviewResponse:
    _ensure_schema(session)
    dataset = get_dataset_or_404(session, dataset_id)
    samples = _load_batch_samples(session, dataset_id, request.sample_ids)
    policy = _policy_values(dataset)
    current_types = defect_types_by_sample(session, request.sample_ids)
    defect_types = _dataset_defect_types(session, dataset_id)
    _validate_operation_references(request.operation, defect_types)

    items: list[BatchTriagePreviewItem] = []
    expected_samples: list[BatchTriageExpectedSample] = []
    for sample in samples:
        sample_id = sample.id or 0
        current_ids = sorted(item.id or 0 for item in current_types.get(sample_id, []))
        before = _batch_state(
            sample,
            current_ids,
            current_policy_version=dataset.triage_policy_version,
        )
        expected_samples.append(
            BatchTriageExpectedSample(
                sample_id=sample_id,
                expected_version=sample.triage_version,
                expected_file_hash=sample.file_hash,
            )
        )
        errors: list[str] = []
        payload: SampleTriageWrite | None = None
        try:
            payload = _batch_payload(sample, current_ids, request.operation)
            _validate_batch_payload(policy, payload, defect_types)
        except ValidationError as exc:
            errors.append(_batch_validation_message(exc))
        except TriageValidationError as exc:
            errors.append(str(exc))

        changed = bool(
            payload is not None
            and not errors
            and not _batch_payload_is_unchanged(
                sample,
                current_ids,
                payload,
                current_policy_version=dataset.triage_policy_version,
            )
        )
        after = None
        if payload is not None:
            after = BatchTriageState(
                triage_status=payload.triage_status,
                ok_grade=payload.ok_grade,
                defect_severity=payload.defect_severity,
                defect_type_ids=payload.defect_type_ids,
                primary_defect_type_id=payload.primary_defect_type_id,
                triage_note=payload.triage_note,
                triage_version=sample.triage_version + (1 if changed else 0),
                outdated=False if changed else before.outdated,
            )
        items.append(
            BatchTriagePreviewItem(
                sample_id=sample_id,
                relative_path=sample.relative_path,
                expected_version=sample.triage_version,
                expected_file_hash=sample.file_hash,
                before=before,
                after=after,
                changed=changed,
                errors=errors,
            )
        )

    blocked = sum(bool(item.errors) for item in items)
    changed = sum(item.changed for item in items)
    unchanged = len(items) - changed - blocked
    preview_hash = _batch_preview_hash(
        dataset_id,
        dataset.triage_policy_version,
        request.operation,
        expected_samples,
    )
    return BatchTriagePreviewResponse(
        dataset_id=dataset_id,
        dataset_revision=dataset.revision,
        policy_version=dataset.triage_policy_version,
        requested=len(items),
        changed=changed,
        unchanged=unchanged,
        blocked=blocked,
        can_apply=blocked == 0 and changed > 0,
        preview_hash=preview_hash,
        expected_samples=expected_samples,
        items=items,
    )


def commit_batch_triage(
    session: Session,
    dataset_id: int,
    request: BatchTriageCommitRequest,
) -> BatchTriageCommitResponse:
    _ensure_schema(session)
    expected_hash = _batch_preview_hash(
        dataset_id,
        request.policy_version,
        request.operation,
        request.expected_samples,
    )
    if request.preview_hash != expected_hash:
        raise TriageConflictError("批量预览内容已变化，请重新预览后提交。")

    dataset = get_dataset_or_404(session, dataset_id)
    if dataset.triage_policy_version != request.policy_version:
        raise TriageConflictError("分拣层级已变化，请重新预览后提交。")
    sample_ids = [item.sample_id for item in request.expected_samples]
    samples = _load_batch_samples(session, dataset_id, sample_ids)
    expected_by_id = {item.sample_id: item for item in request.expected_samples}
    for sample in samples:
        expected = expected_by_id[sample.id or 0]
        if (
            sample.triage_version != expected.expected_version
            or sample.file_hash != expected.expected_file_hash
        ):
            raise TriageConflictError(
                "至少一个样本的分拣结果或图片内容已变化；本次批量操作未写入，请重新预览。"
            )

    current_types = defect_types_by_sample(session, sample_ids)
    defect_types = _dataset_defect_types(session, dataset_id)
    _validate_operation_references(request.operation, defect_types)
    prepared: list[tuple[Sample, SampleTriageWrite]] = []
    for sample in samples:
        sample_id = sample.id or 0
        current_ids = sorted(item.id or 0 for item in current_types.get(sample_id, []))
        try:
            payload = _batch_payload(sample, current_ids, request.operation)
        except ValidationError as exc:
            raise TriageValidationError(_batch_validation_message(exc)) from exc
        _validate_batch_payload(_policy_values(dataset), payload, defect_types)
        if not _batch_payload_is_unchanged(
            sample,
            current_ids,
            payload,
            current_policy_version=dataset.triage_policy_version,
        ):
            prepared.append((sample, payload))

    if not prepared:
        return BatchTriageCommitResponse(
            dataset_id=dataset_id,
            dataset_revision=dataset.revision,
            requested=len(samples),
            updated=0,
            unchanged=len(samples),
        )

    now = utc_now().astimezone(timezone.utc)
    try:
        for sample, payload in prepared:
            sample_id = sample.id or 0
            is_reset = payload.triage_status == "untriaged"
            result = session.connection().execute(
                update(Sample)
                .where(
                    Sample.id == sample_id,
                    Sample.triage_version == payload.expected_version,
                    Sample.file_hash == payload.expected_file_hash,
                )
                .values(
                    triage_status=payload.triage_status,
                    ok_grade=payload.ok_grade,
                    defect_severity=payload.defect_severity,
                    primary_defect_type_id=payload.primary_defect_type_id,
                    triage_note=payload.triage_note,
                    triage_version=Sample.triage_version + 1,
                    triaged_at=None if is_reset else now,
                    triage_policy_version=(
                        None if is_reset else dataset.triage_policy_version
                    ),
                    triaged_file_hash=None if is_reset else sample.file_hash,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise TriageConflictError(
                    "至少一个样本在提交期间被修改；本次批量操作已整批回滚。"
                )
            session.connection().execute(
                delete(SampleDefectLink).where(
                    SampleDefectLink.sample_id == sample_id
                )
            )
            if payload.defect_type_ids:
                session.connection().execute(
                    insert(SampleDefectLink),
                    [
                        {
                            "sample_id": sample_id,
                            "defect_type_id": defect_type_id,
                        }
                        for defect_type_id in payload.defect_type_ids
                    ],
                )
        revision = bump_dataset_revision(session, dataset_id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise TriageConflictError(
            "批量分拣写入发生数据冲突；本次操作已整批回滚。"
        ) from exc
    except Exception:
        session.rollback()
        raise

    return BatchTriageCommitResponse(
        dataset_id=dataset_id,
        dataset_revision=revision,
        requested=len(samples),
        updated=len(prepared),
        unchanged=len(samples) - len(prepared),
    )


def _triage_filters(
    statement,
    dataset_id: int,
    *,
    search: str | None,
    split: str | None,
    triage_status: str | None,
    ok_grade: str | None,
    defect_severity: str | None,
    defect_type_id: int | None,
):
    statement = statement.where(
        Sample.dataset_id == dataset_id,
        Sample.file_type == "image",
        Sample.file_status == "normal",
    )
    if search:
        pattern = f"%{search.strip().casefold()}%"
        statement = statement.where(
            or_(
                func.lower(Sample.filename).like(pattern),
                func.lower(Sample.relative_path).like(pattern),
            )
        )
    if split:
        statement = statement.where(
            Sample.split.is_(None) if split == "unassigned" else Sample.split == split
        )
    if triage_status:
        statement = statement.where(Sample.triage_status == triage_status)
    if ok_grade:
        statement = statement.where(Sample.ok_grade == ok_grade)
    if defect_severity:
        statement = statement.where(Sample.defect_severity == defect_severity)
    if defect_type_id:
        statement = statement.where(
            exists(
                select(SampleDefectLink.sample_id).where(
                    SampleDefectLink.sample_id == Sample.id,
                    SampleDefectLink.defect_type_id == defect_type_id,
                )
            )
        )
    return statement


def get_triage_navigation(
    session: Session,
    dataset_id: int,
    *,
    sample_id: int | None = None,
    queue_scope: TriageQueueScope = "untriaged",
    search: str | None = None,
    split: str | None = None,
    triage_status: str | None = None,
    ok_grade: str | None = None,
    defect_severity: str | None = None,
    defect_type_id: int | None = None,
) -> TriageNavigationResponse:
    _ensure_schema(session)
    dataset = get_dataset_or_404(session, dataset_id)
    validate_triage_filters(
        session,
        dataset_id,
        ok_grade=ok_grade if queue_scope == "current_filter" else None,
        defect_severity=defect_severity if queue_scope == "current_filter" else None,
        defect_type_id=defect_type_id if queue_scope == "current_filter" else None,
    )
    effective_status = triage_status
    effective_split = split
    if queue_scope == "untriaged":
        effective_status = "untriaged"
    elif queue_scope == "pending":
        effective_status = "pending"
    elif queue_scope == "current_split" and not effective_split and sample_id is not None:
        current = session.get(Sample, sample_id)
        if current is not None and current.dataset_id == dataset_id:
            effective_split = current.split or "unassigned"

    def filtered(statement):
        return _triage_filters(
            statement,
            dataset_id,
            search=search if queue_scope == "current_filter" else None,
            split=effective_split if queue_scope in {"current_filter", "current_split"} else None,
            triage_status=effective_status,
            ok_grade=ok_grade if queue_scope == "current_filter" else None,
            defect_severity=defect_severity if queue_scope == "current_filter" else None,
            defect_type_id=defect_type_id if queue_scope == "current_filter" else None,
        )

    total = int(
        session.exec(select(func.count()).select_from(filtered(select(Sample.id)).subquery())).one()
    )
    current = None
    if sample_id is not None:
        current = session.exec(filtered(select(Sample)).where(Sample.id == sample_id)).first()
    if current is None:
        current = session.exec(
            filtered(select(Sample)).order_by(func.lower(Sample.relative_path), Sample.id).limit(1)
        ).first()
    if current is None:
        return TriageNavigationResponse(
            total=total,
            remaining=0,
            queue_scope=queue_scope,
        )

    before = or_(
        func.lower(Sample.relative_path) < current.relative_path.casefold(),
        (
            (func.lower(Sample.relative_path) == current.relative_path.casefold())
            & (Sample.id < (current.id or 0))
        ),
    )
    after = or_(
        func.lower(Sample.relative_path) > current.relative_path.casefold(),
        (
            (func.lower(Sample.relative_path) == current.relative_path.casefold())
            & (Sample.id > (current.id or 0))
        ),
    )
    previous_id = session.exec(
        filtered(select(Sample.id))
        .where(before)
        .order_by(func.lower(Sample.relative_path).desc(), Sample.id.desc())
        .limit(1)
    ).first()
    next_id = session.exec(
        filtered(select(Sample.id))
        .where(after)
        .order_by(func.lower(Sample.relative_path), Sample.id)
        .limit(1)
    ).first()
    current_index = int(
        session.exec(
            select(func.count()).select_from(filtered(select(Sample.id)).where(before).subquery())
        ).one()
    )
    ids = [item for item in (previous_id, current.id, next_id) if item is not None]
    rows = session.exec(
        select(Sample).where(Sample.id.in_(ids)).options(selectinload(Sample.tags))
    ).all()
    by_id = {item.id: item for item in rows}
    return TriageNavigationResponse(
        current_sample=to_sample_read(current, dataset.triage_policy_version),
        previous_sample=(
            to_sample_read(by_id[int(previous_id)], dataset.triage_policy_version)
            if previous_id is not None
            else None
        ),
        next_sample=(
            to_sample_read(by_id[int(next_id)], dataset.triage_policy_version)
            if next_id is not None
            else None
        ),
        current_index=current_index,
        total=total,
        remaining=max(total - current_index - 1, 0),
        queue_scope=queue_scope,
    )


def get_triage_stats(session: Session, dataset_id: int) -> TriageStats:
    _ensure_schema(session)
    dataset = get_dataset_or_404(session, dataset_id)
    policy = _policy_values(dataset)
    image_filter = (Sample.dataset_id == dataset_id, Sample.file_type == "image")
    total_images = int(session.exec(select(func.count(Sample.id)).where(*image_filter)).one())

    def group(expression, *, include_null: bool = False) -> dict[str, int]:
        key = func.coalesce(expression, "ungraded") if include_null else expression
        rows = session.exec(
            select(key, func.count(Sample.id)).where(*image_filter).group_by(key)
        ).all()
        return {str(value): int(count) for value, count in rows if value is not None}

    defect_rows = session.exec(
        select(DefectType.name, func.count(func.distinct(SampleDefectLink.sample_id)))
        .join(SampleDefectLink, SampleDefectLink.defect_type_id == DefectType.id)
        .join(Sample, Sample.id == SampleDefectLink.sample_id)
        .where(DefectType.dataset_id == dataset_id, Sample.file_type == "image")
        .group_by(DefectType.id, DefectType.name)
    ).all()
    outdated = int(
        session.exec(
            select(func.count(Sample.id)).where(
                *image_filter,
                Sample.triage_status != "untriaged",
                or_(
                    Sample.triaged_file_hash.is_(None),
                    Sample.triaged_file_hash != Sample.file_hash,
                    Sample.triage_policy_version.is_(None),
                    Sample.triage_policy_version != dataset.triage_policy_version,
                ),
            )
        ).one()
    )
    export_bucket = _export_bucket_expression(policy)
    export_rows = session.exec(
        select(export_bucket, func.count(Sample.id))
        .where(
            *image_filter,
            Sample.triage_status.in_(("ok", "ng")),
        )
        .group_by(export_bucket)
    ).all()
    return TriageStats(
        dataset_id=dataset_id,
        total_images=total_images,
        by_status=group(Sample.triage_status),
        by_ok_grade=group(Sample.ok_grade),
        by_severity=group(Sample.defect_severity, include_null=True),
        by_defect_type={name: int(count) for name, count in defect_rows},
        by_export_bucket={
            str(bucket): int(count)
            for bucket, count in export_rows
            if bucket is not None
        },
        outdated=outdated,
    )


def _export_bucket_expression(policy: TriagePolicyValues):
    link_count = (
        select(func.count(SampleDefectLink.defect_type_id))
        .where(SampleDefectLink.sample_id == Sample.id)
        .correlate(Sample)
        .scalar_subquery()
    )
    single_code = (
        select(func.min(DefectType.code))
        .join(SampleDefectLink, SampleDefectLink.defect_type_id == DefectType.id)
        .where(SampleDefectLink.sample_id == Sample.id)
        .correlate(Sample)
        .scalar_subquery()
    )
    primary_code = (
        select(DefectType.code)
        .where(DefectType.id == Sample.primary_defect_type_id)
        .correlate(Sample)
        .scalar_subquery()
    )
    defect_bucket = case(
        (primary_code.is_not(None), primary_code),
        (link_count == 0, literal("unknown")),
        (link_count == 1, single_code),
        else_=literal("multi_defect"),
    )
    severity_bucket = func.coalesce(Sample.defect_severity, "ungraded")
    ok_bucket = (
        literal("ok/") + cast(func.coalesce(Sample.ok_grade, "ungraded"), String)
        if policy.split_ok
        else literal("ok")
    )
    if policy.ng_grouping == "none":
        ng_bucket = literal("ng")
    elif policy.ng_grouping == "defect_type":
        ng_bucket = literal("ng/") + cast(defect_bucket, String)
    elif policy.ng_grouping == "severity":
        ng_bucket = literal("ng/") + cast(severity_bucket, String)
    else:
        ng_bucket = (
            literal("ng/")
            + cast(defect_bucket, String)
            + literal("/")
            + cast(severity_bucket, String)
        )
    return case(
        (Sample.triage_status == "ok", ok_bucket),
        (Sample.triage_status == "ng", ng_bucket),
        else_=None,
    )
