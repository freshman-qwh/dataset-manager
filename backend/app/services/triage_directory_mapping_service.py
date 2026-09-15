from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.defect_type import DefectType
from app.models.sample import Sample
from app.schemas.triage import TriagePolicyRead
from app.schemas.triage_directory_mapping import (
    TriageDirectoryMappingPreviewItem,
    TriageDirectoryMappingPreviewRequest,
    TriageDirectoryMappingPreviewResponse,
    TriageDirectoryMappingRule,
    TriageDirectorySource,
    TriageDirectorySourceResponse,
)
from app.services import dataset_service, triage_service


PLAN_LIFETIME = timedelta(hours=1)
PLAN_VERSION = 1
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200


class TriageDirectoryMappingError(ValueError):
    pass


class TriageDirectoryMappingPlanNotFoundError(TriageDirectoryMappingError):
    pass


class TriageDirectoryMappingPlanExpiredError(TriageDirectoryMappingError):
    pass


class TriageDirectoryMappingPlanChangedError(TriageDirectoryMappingError):
    pass


def triage_directory_mapping_plan_root() -> Path:
    return get_settings().storage_root / "triage-directory-mapping-plans"


def list_triage_source_directories(
    session: Session,
    dataset_id: int,
    *,
    search: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> TriageDirectorySourceResponse:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    policy = triage_service.get_triage_policy(session, dataset_id)
    rows = session.exec(
        select(
            Sample.relative_path,
            Sample.triage_status,
        ).where(
            Sample.dataset_id == dataset_id,
            Sample.file_type == "image",
        )
    ).all()
    grouped: dict[str, dict[str, object]] = {}
    for relative_path, triage_status in rows:
        directory = _sample_directory(str(relative_path))
        group = grouped.setdefault(
            directory,
            {"status_counts": Counter(), "examples": []},
        )
        status_counts = group["status_counts"]
        if isinstance(status_counts, Counter):
            status_counts[str(triage_status or "untriaged")] += 1
        examples = group["examples"]
        if isinstance(examples, list) and len(examples) < 3:
            examples.append(str(relative_path))

    normalized_search = search.strip().casefold() if search else ""
    directories = sorted(
        (
            directory
            for directory in grouped
            if not normalized_search or normalized_search in directory.casefold()
        ),
        key=lambda value: (value.casefold(), value),
    )
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    page_count = max((len(directories) + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(max(page, 1), page_count)
    start = (safe_page - 1) * safe_page_size
    items: list[TriageDirectorySource] = []
    for directory in directories[start : start + safe_page_size]:
        group = grouped[directory]
        status_counts = Counter(group["status_counts"])
        image_count = sum(status_counts.values())
        untriaged_count = status_counts.get("untriaged", 0)
        items.append(
            TriageDirectorySource(
                directory=directory,
                image_count=image_count,
                untriaged_count=untriaged_count,
                existing_count=image_count - untriaged_count,
                status_counts=dict(sorted(status_counts.items())),
                examples=list(group["examples"]),
            )
        )
    return TriageDirectorySourceResponse(
        dataset_id=dataset_id,
        dataset_revision=dataset.revision,
        triage_policy=policy,
        defect_types=triage_service.list_defect_types(
            session,
            dataset_id,
            include_inactive=False,
        ),
        total_directories=len(directories),
        total_images=len(rows),
        page=safe_page,
        page_size=safe_page_size,
        page_count=page_count,
        items=items,
    )


def create_triage_directory_mapping_preview(
    session: Session,
    dataset_id: int,
    payload: TriageDirectoryMappingPreviewRequest,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> TriageDirectoryMappingPreviewResponse:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    policy = triage_service.get_triage_policy(session, dataset_id)
    rules = _validated_rules(session, dataset_id, policy, payload.mappings)
    samples = list(
        session.exec(
            select(Sample)
            .where(
                Sample.dataset_id == dataset_id,
                Sample.file_type == "image",
            )
            .order_by(Sample.relative_path, Sample.id)
        ).all()
    )
    observed_directories = {_sample_directory(sample.relative_path).casefold() for sample in samples}
    unknown_directories = sorted(
        rule.source_directory
        for rule in rules.values()
        if rule.source_directory.casefold() not in observed_directories
    )
    if unknown_directories:
        display = "、".join(directory or "（根目录）" for directory in unknown_directories[:5])
        raise TriageDirectoryMappingError(f"来源目录不存在或没有图片：{display}")

    sample_ids = [sample.id or 0 for sample in samples]
    current_defects = triage_service.defect_types_by_sample(session, sample_ids)
    items: list[dict[str, object]] = []
    decisions: Counter[str] = Counter()
    mapped_sample_count = 0
    for sample in samples:
        directory = _sample_directory(sample.relative_path)
        rule = rules.get(directory.casefold())
        item = _preview_sample(
            sample,
            directory=directory,
            rule=rule,
            policy=policy,
            current_defect_ids=[item.id or 0 for item in current_defects.get(sample.id or 0, [])],
            existing_behavior=payload.existing_behavior,
        )
        if rule is not None:
            mapped_sample_count += 1
        decisions[str(item["decision"])] += 1
        items.append(item)

    created_at = datetime.now(timezone.utc)
    plan_id = str(uuid4())
    plan: dict[str, object] = {
        "plan_version": PLAN_VERSION,
        "plan_id": plan_id,
        "dataset_id": dataset_id,
        "dataset_revision": dataset.revision,
        "triage_policy_version": policy.version,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + PLAN_LIFETIME).isoformat(),
        "existing_behavior": payload.existing_behavior,
        "mappings": [rule.model_dump(mode="json") for rule in rules.values()],
        "total_images": len(items),
        "mapped_sample_count": mapped_sample_count,
        "change_count": decisions["apply"],
        "unchanged_count": decisions["unchanged"],
        "skipped_existing_count": decisions["skipped_existing"],
        "unmapped_count": decisions["unmapped"],
        "unavailable_count": decisions["file_unavailable"],
        "items": items,
    }
    plan_hash = _plan_digest(plan)
    plan["plan_hash"] = plan_hash
    _write_plan(plan_id, plan)
    return _preview_response(plan, page=page, page_size=page_size)


def get_triage_directory_mapping_preview(
    dataset_id: int,
    plan_id: str,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> TriageDirectoryMappingPreviewResponse:
    plan = load_triage_directory_mapping_plan(plan_id)
    if int(plan["dataset_id"]) != dataset_id:
        raise TriageDirectoryMappingPlanNotFoundError("未找到该数据集的旧目录映射预览。")
    return _preview_response(plan, page=page, page_size=page_size)


def validate_plan_for_job(
    session: Session,
    dataset_id: int,
    plan_id: str,
    expected_hash: str,
) -> dict[str, object]:
    plan = load_triage_directory_mapping_plan(plan_id, expected_hash=expected_hash)
    if int(plan["dataset_id"]) != dataset_id:
        raise TriageDirectoryMappingPlanNotFoundError("未找到该数据集的旧目录映射计划。")
    if datetime.fromisoformat(str(plan["expires_at"])) <= datetime.now(timezone.utc):
        raise TriageDirectoryMappingPlanExpiredError("旧目录映射预览已过期，请重新预览。")
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    if dataset.revision != int(plan["dataset_revision"]):
        raise TriageDirectoryMappingPlanChangedError("预览后数据集已变化，请重新预览。")
    if dataset.triage_policy_version != int(plan["triage_policy_version"]):
        raise TriageDirectoryMappingPlanChangedError("预览后分拣层级已变化，请重新预览。")
    return plan


def load_triage_directory_mapping_plan(
    plan_id: str,
    *,
    expected_hash: str | None = None,
) -> dict[str, object]:
    path = _plan_path(plan_id)
    if not path.is_file():
        raise TriageDirectoryMappingPlanNotFoundError("旧目录映射预览不存在或已被清理。")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TriageDirectoryMappingPlanChangedError("旧目录映射计划无法读取。") from exc
    if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
        raise TriageDirectoryMappingPlanChangedError("旧目录映射计划内容无效。")
    stored_hash = plan.get("plan_hash")
    content = {key: value for key, value in plan.items() if key != "plan_hash"}
    actual_hash = _plan_digest(content)
    if not isinstance(stored_hash, str) or stored_hash != actual_hash:
        raise TriageDirectoryMappingPlanChangedError("旧目录映射计划校验失败，请重新预览。")
    if expected_hash is not None and stored_hash != expected_hash:
        raise TriageDirectoryMappingPlanChangedError("旧目录映射计划版本不匹配，请重新预览。")
    return plan


def _validated_rules(
    session: Session,
    dataset_id: int,
    policy: TriagePolicyRead,
    mappings: list[TriageDirectoryMappingRule],
) -> dict[str, TriageDirectoryMappingRule]:
    active_types = {
        item.id: item
        for item in session.exec(
            select(DefectType).where(
                DefectType.dataset_id == dataset_id,
                DefectType.is_active.is_(True),
            )
        ).all()
        if item.id is not None
    }
    result: dict[str, TriageDirectoryMappingRule] = {}
    for rule in mappings:
        directory = _canonical_directory(rule.source_directory)
        normalized = rule.model_copy(update={"source_directory": directory})
        if normalized.triage_status == "ok":
            if policy.split_ok and normalized.ok_grade is None:
                raise TriageDirectoryMappingError(
                    f"目录“{directory or '（根目录）'}”映射为 OK 时必须明确选择完全 OK 或勉强 OK。"
                )
            if not policy.split_ok and normalized.ok_grade is not None:
                raise TriageDirectoryMappingError("当前层级使用统一 OK，不能设置 OK 等级。")
        if normalized.triage_status == "ng":
            allows_type = policy.ng_grouping in {"defect_type", "defect_type_and_severity"}
            allows_severity = policy.ng_grouping in {"severity", "defect_type_and_severity"}
            if normalized.defect_type_id is not None and not allows_type:
                raise TriageDirectoryMappingError("当前 NG 层级未启用缺陷类别。")
            if normalized.defect_severity is not None and not allows_severity:
                raise TriageDirectoryMappingError("当前 NG 层级未启用缺陷程度。")
            if (
                normalized.defect_type_id is not None
                and normalized.defect_type_id not in active_types
            ):
                raise TriageDirectoryMappingError("映射选择的缺陷类型不存在、已停用或不属于当前数据集。")
        result[directory.casefold()] = normalized
    return result


def _preview_sample(
    sample: Sample,
    *,
    directory: str,
    rule: TriageDirectoryMappingRule | None,
    policy: TriagePolicyRead,
    current_defect_ids: list[int],
    existing_behavior: str,
) -> dict[str, object]:
    base: dict[str, object] = {
        "sample_id": sample.id or 0,
        "relative_path": sample.relative_path,
        "source_directory": directory,
        "current_status": sample.triage_status,
        "expected_triage_version": sample.triage_version,
        "expected_file_hash": sample.file_hash,
        "target_status": None,
        "target_ok_grade": None,
        "target_defect_severity": None,
        "target_defect_type_id": None,
        "target_defect_type_ids": [],
        "triage_note": sample.triage_note,
    }
    if rule is None:
        return {**base, "decision": "unmapped"}
    base.update(
        {
            "target_status": rule.triage_status,
            "target_ok_grade": rule.ok_grade,
            "target_defect_severity": rule.defect_severity,
            "target_defect_type_id": rule.defect_type_id,
            "target_defect_type_ids": [rule.defect_type_id] if rule.defect_type_id else [],
        }
    )
    if sample.file_status != "normal":
        return {**base, "decision": "file_unavailable"}
    target_ids = list(base["target_defect_type_ids"])
    unchanged = (
        sample.triage_status == rule.triage_status
        and sample.ok_grade == rule.ok_grade
        and sample.defect_severity == rule.defect_severity
        and sample.primary_defect_type_id == rule.defect_type_id
        and sorted(current_defect_ids) == target_ids
        and sample.triaged_file_hash == sample.file_hash
        and sample.triage_policy_version == policy.version
    )
    if unchanged:
        return {**base, "decision": "unchanged"}
    if sample.triage_status != "untriaged" and existing_behavior == "skip":
        return {**base, "decision": "skipped_existing"}
    return {**base, "decision": "apply"}


def _preview_response(
    plan: dict[str, object],
    *,
    page: int,
    page_size: int,
) -> TriageDirectoryMappingPreviewResponse:
    items = plan.get("items")
    if not isinstance(items, list):
        raise TriageDirectoryMappingPlanChangedError("旧目录映射计划缺少样本列表。")
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    page_count = max((len(items) + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(max(page, 1), page_count)
    start = (safe_page - 1) * safe_page_size
    visible_items = items[start : start + safe_page_size]
    public = {
        key: value
        for key, value in plan.items()
        if key
        not in {
            "items",
            "mappings",
            "dataset_revision",
            "triage_policy_version",
            "plan_version",
        }
    }
    return TriageDirectoryMappingPreviewResponse(
        **public,
        blocked=int(plan["change_count"]) == 0,
        page=safe_page,
        page_size=safe_page_size,
        page_count=page_count,
        items=[TriageDirectoryMappingPreviewItem.model_validate(item) for item in visible_items],
    )


def _sample_directory(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    parent = PurePosixPath(normalized).parent.as_posix()
    return "" if parent == "." else parent


def _canonical_directory(value: str) -> str:
    if not value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TriageDirectoryMappingError("来源目录必须是数据集内的安全相对目录。")
    return path.as_posix()


def _write_plan(plan_id: str, plan: dict[str, object]) -> None:
    path = _plan_path(plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.part"
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        temporary.write_text(payload, encoding="utf-8")
        if path.exists():
            raise FileExistsError("Triage directory mapping plan already exists.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _plan_path(plan_id: str) -> Path:
    try:
        normalized = str(UUID(plan_id))
    except (ValueError, AttributeError) as exc:
        raise TriageDirectoryMappingPlanNotFoundError("旧目录映射预览编号无效。") from exc
    if normalized != plan_id:
        raise TriageDirectoryMappingPlanNotFoundError("旧目录映射预览编号无效。")
    root = triage_directory_mapping_plan_root().resolve()
    path = (root / f"plan-{normalized}.json").resolve()
    if path.parent != root:
        raise TriageDirectoryMappingPlanNotFoundError("旧目录映射预览编号无效。")
    return path


def _plan_digest(plan: dict[str, object]) -> str:
    encoded = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
