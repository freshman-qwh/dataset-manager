from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import unicodedata
from uuid import UUID, uuid4

from sqlmodel import Session

from app.models.defect_type import DefectType
from app.models.sample import Sample
from app.schemas.directory_export import (
    DirectoryExportPreviewItem,
    DirectoryExportPreviewRequest,
    DirectoryExportPreviewResponse,
)
from app.schemas.triage import TriagePolicyRead
from app.services import dataset_service, sample_service, triage_service
from app.core.config import get_settings


PLAN_LIFETIME = timedelta(hours=1)
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200
PLAN_VERSION = 1
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class DirectoryExportError(ValueError):
    pass


class DirectoryExportPlanNotFoundError(DirectoryExportError):
    pass


class DirectoryExportPlanExpiredError(DirectoryExportError):
    pass


class DirectoryExportPlanChangedError(DirectoryExportError):
    pass


def directory_export_plan_root() -> Path:
    return get_settings().storage_root / "directory-export-plans"


def directory_export_output_root() -> Path:
    return get_settings().storage_root / "directory-exports"


def create_directory_export_preview(
    session: Session,
    dataset_id: int,
    payload: DirectoryExportPreviewRequest,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> DirectoryExportPreviewResponse:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    triage_service.validate_triage_filters(
        session,
        dataset_id,
        ok_grade=payload.sample_query.ok_grade,
        defect_severity=payload.sample_query.defect_severity,
        defect_type_id=payload.sample_query.defect_type_id,
    )
    policy = triage_service.get_triage_policy(session, dataset_id)
    query = payload.sample_query
    if query.file_type not in {None, "image"}:
        samples = []
    else:
        samples = sample_service.get_filtered_samples(
            session,
            dataset_id,
            search=query.search,
            file_type="image",
            file_status=query.file_status,
            tag=query.tag,
            split=query.split,
            review_status=query.review_status,
            annotation_progress=query.annotation_progress,
            sample_ids=query.sample_ids,
            sort_by=query.sort_by,
            sort_order=query.sort_order,
            triage_status=query.triage_status,
            ok_grade=query.ok_grade,
            defect_severity=query.defect_severity,
            defect_type_id=query.defect_type_id,
            triage_outdated=query.triage_outdated,
        )
    sample_ids = [sample.id for sample in samples if sample.id is not None]
    defects = triage_service.defect_types_by_sample(session, sample_ids)
    created_at = datetime.now(timezone.utc)
    plan_id = str(uuid4())
    output_name = _output_name(
        dataset_id,
        payload.run_name,
        created_at,
        plan_id,
        payload.delivery,
    )

    items: list[dict[str, object]] = []
    directory_counts: Counter[str] = Counter()
    exclusion_counts: Counter[str] = Counter()
    total_bytes = 0
    for sample in samples:
        item = _plan_sample(
            sample,
            policy_version=policy.version,
            policy=policy,
            defects=defects.get(sample.id or 0, []),
            payload=payload,
        )
        items.append(item)
        if item["included"]:
            bucket = str(item["bucket"])
            directory_counts[bucket] += 1
            total_bytes += int(item["file_size"])
        else:
            exclusion_counts[str(item["exclusion_reason"])] += 1

    included_count = sum(1 for item in items if item["included"])
    warnings = _preview_warnings(exclusion_counts, payload)
    plan: dict[str, object] = {
        "plan_version": PLAN_VERSION,
        "plan_id": plan_id,
        "dataset_id": dataset_id,
        "dataset_revision": dataset.revision,
        "triage_policy_version": policy.version,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + PLAN_LIFETIME).isoformat(),
        "delivery": payload.delivery,
        "output_name": output_name,
        "request": payload.model_dump(mode="json"),
        "triage_policy": policy.model_dump(mode="json"),
        "selected_count": len(items),
        "included_count": included_count,
        "excluded_count": len(items) - included_count,
        "total_bytes": total_bytes,
        "directory_counts": dict(sorted(directory_counts.items())),
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "warnings": warnings,
        "items": items,
    }
    plan_hash = _plan_digest(plan)
    plan["plan_hash"] = plan_hash
    _write_plan(plan_id, plan)
    return _preview_response(plan, page=page, page_size=page_size)


def get_directory_export_preview(
    dataset_id: int,
    plan_id: str,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> DirectoryExportPreviewResponse:
    plan = load_directory_export_plan(plan_id)
    if int(plan["dataset_id"]) != dataset_id:
        raise DirectoryExportPlanNotFoundError("未找到该数据集的导出预览。")
    return _preview_response(plan, page=page, page_size=page_size)


def validate_plan_for_job(
    session: Session,
    dataset_id: int,
    plan_id: str,
    expected_hash: str,
) -> dict[str, object]:
    plan = load_directory_export_plan(plan_id, expected_hash=expected_hash)
    if int(plan["dataset_id"]) != dataset_id:
        raise DirectoryExportPlanNotFoundError("未找到该数据集的导出计划。")
    expires_at = datetime.fromisoformat(str(plan["expires_at"]))
    if expires_at <= datetime.now(timezone.utc):
        raise DirectoryExportPlanExpiredError("导出预览已过期，请重新预检。")
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    if dataset.revision != int(plan["dataset_revision"]):
        raise DirectoryExportPlanChangedError("预检后数据集已变化，请重新预检。")
    if dataset.triage_policy_version != int(plan["triage_policy_version"]):
        raise DirectoryExportPlanChangedError("预检后分拣层级已变化，请重新预检。")
    return plan


def load_directory_export_plan(
    plan_id: str,
    *,
    expected_hash: str | None = None,
) -> dict[str, object]:
    path = _plan_path(plan_id)
    if not path.is_file():
        raise DirectoryExportPlanNotFoundError("导出预览不存在或已被清理。")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DirectoryExportPlanChangedError("导出计划无法读取。") from exc
    if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
        raise DirectoryExportPlanChangedError("导出计划内容无效。")
    stored_hash = plan.get("plan_hash")
    content = {key: value for key, value in plan.items() if key != "plan_hash"}
    actual_hash = _plan_digest(content)
    if not isinstance(stored_hash, str) or stored_hash != actual_hash:
        raise DirectoryExportPlanChangedError("导出计划校验失败，请重新预检。")
    if expected_hash is not None and stored_hash != expected_hash:
        raise DirectoryExportPlanChangedError("导出计划版本不匹配，请重新预检。")
    return plan


def _plan_sample(
    sample: Sample,
    *,
    policy_version: int,
    policy: TriagePolicyRead,
    defects: list[DefectType],
    payload: DirectoryExportPreviewRequest,
) -> dict[str, object]:
    sample_id = sample.id or 0
    status = sample.triage_status or "untriaged"
    outdated = status != "untriaged" and (
        sample.triaged_file_hash != sample.file_hash
        or sample.triage_policy_version != policy_version
    )
    bucket = triage_service.configured_export_bucket(
        policy,
        triage_status=status,
        ok_grade=sample.ok_grade,
        defect_severity=sample.defect_severity,
        defect_types=defects,
        primary_defect_type_id=sample.primary_defect_type_id,
    )
    exclusion_reason: str | None = None
    if sample.file_status != "normal":
        exclusion_reason = "file_unavailable"
    elif outdated and not payload.include_outdated:
        exclusion_reason = "triage_outdated"
    elif status == "pending" and not payload.include_pending:
        exclusion_reason = "pending_excluded"
    elif status == "untriaged" and not payload.include_untriaged:
        exclusion_reason = "untriaged_excluded"
    elif status == "pending":
        bucket = "pending"
    elif status == "untriaged":
        bucket = "untriaged"
    elif bucket is None:
        exclusion_reason = "status_not_exportable"

    source = Path(sample.absolute_path)
    file_size = int(sample.file_size)
    if exclusion_reason is None:
        try:
            if not source.is_file():
                exclusion_reason = "source_missing"
            else:
                file_size = source.stat().st_size
        except OSError:
            exclusion_reason = "source_unreadable"

    target_relative_path = None
    if exclusion_reason is None and bucket is not None:
        filename = f"{sample_id}__{_safe_component(sample.filename)}"
        target_relative_path = f"{bucket}/{filename}"

    return {
        "sample_id": sample_id,
        "source_absolute_path": sample.absolute_path,
        "source_relative_path": sample.relative_path,
        "target_relative_path": target_relative_path,
        "bucket": bucket if exclusion_reason is None else None,
        "file_size": file_size,
        "file_hash": sample.file_hash,
        "triage_status": status,
        "ok_grade": sample.ok_grade,
        "defect_severity": sample.defect_severity,
        "defect_types": [
            {"id": item.id, "name": item.name, "code": item.code}
            for item in defects
        ],
        "primary_defect_type_id": sample.primary_defect_type_id,
        "triage_note": sample.triage_note,
        "triage_policy_version": sample.triage_policy_version,
        "outdated": outdated,
        "included": exclusion_reason is None,
        "exclusion_reason": exclusion_reason,
    }


def _preview_response(
    plan: dict[str, object],
    *,
    page: int,
    page_size: int,
) -> DirectoryExportPreviewResponse:
    items = plan.get("items")
    if not isinstance(items, list):
        raise DirectoryExportPlanChangedError("导出计划缺少样本列表。")
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    page_count = max((len(items) + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(max(page, 1), page_count)
    start = (safe_page - 1) * safe_page_size
    visible_items = items[start : start + safe_page_size]
    content = {
        key: value
        for key, value in plan.items()
        if key not in {"items", "request", "dataset_revision", "triage_policy_version", "plan_version"}
    }
    return DirectoryExportPreviewResponse(
        **content,
        blocked=int(plan["included_count"]) == 0,
        page=safe_page,
        page_size=safe_page_size,
        page_count=page_count,
        items=[DirectoryExportPreviewItem.model_validate(item) for item in visible_items],
    )


def _preview_warnings(
    exclusion_counts: Counter[str],
    payload: DirectoryExportPreviewRequest,
) -> list[str]:
    warnings: list[str] = []
    if exclusion_counts.get("triage_outdated"):
        warnings.append("存在过期判定，默认不会导出；请复核或显式允许。")
    if exclusion_counts.get("file_unavailable") or exclusion_counts.get("source_missing"):
        warnings.append("存在不可用或缺失文件，这些样本不会导出。")
    if payload.include_pending:
        warnings.append("待定样本将进入 pending 目录，不视为 OK 或 NG。")
    if payload.include_untriaged:
        warnings.append("未分拣样本将进入 untriaged 目录。")
    return warnings


def _output_name(
    dataset_id: int,
    run_name: str | None,
    created_at: datetime,
    plan_id: str,
    delivery: str,
) -> str:
    prefix = _safe_component(run_name or f"dataset-{dataset_id}", max_length=48)
    timestamp = created_at.strftime("%Y%m%d-%H%M%S")
    base = f"{prefix}-triage-{timestamp}-{plan_id[:8]}"
    return f"{base}.zip" if delivery == "zip" else base


def _safe_component(value: str, *, max_length: int = 180) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    if not normalized:
        normalized = "unnamed"
    stem = Path(normalized).stem.casefold()
    if stem in _WINDOWS_RESERVED:
        normalized = f"_{normalized}"
    if len(normalized) <= max_length:
        return normalized
    suffix = Path(normalized).suffix[:20]
    stem_value = normalized[: max_length - len(suffix)].rstrip(" .")
    return f"{stem_value}{suffix}" or "unnamed"


def _write_plan(plan_id: str, plan: dict[str, object]) -> None:
    path = _plan_path(plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.part"
    payload = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        temporary.write_text(payload, encoding="utf-8")
        if path.exists():
            raise FileExistsError("Directory export plan already exists.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _plan_path(plan_id: str) -> Path:
    try:
        normalized = str(UUID(plan_id))
    except (ValueError, AttributeError) as exc:
        raise DirectoryExportPlanNotFoundError("导出预览编号无效。") from exc
    if normalized != plan_id:
        raise DirectoryExportPlanNotFoundError("导出预览编号无效。")
    root = directory_export_plan_root().resolve()
    path = (root / f"plan-{normalized}.json").resolve()
    if path.parent != root:
        raise DirectoryExportPlanNotFoundError("导出预览编号无效。")
    return path


def _plan_digest(plan: dict[str, object]) -> str:
    encoded = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
