"""Bounded, immutable plans in application storage; no raw-data sidecars."""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session

from app.core.config import get_settings
from app.schemas.industrial import FrozenPlanRead
from app.services.dataset_service import get_dataset_or_404


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan_path(plan_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", plan_id):
        raise HTTPException(404, "找不到预览计划。")
    return get_settings().storage_root / "industrial-plans" / f"{plan_id}.json"


def freeze(kind: str, dataset_id: int, revision: int, rows: list[dict], summary: dict, *, confirmation: str | None = None, **extra) -> dict:
    if len(rows) > 10000:
        raise HTTPException(422, "本次最多预览 10000 张图片，请缩小范围。")
    plan = dict(plan_id=uuid4().hex, kind=kind, dataset_id=dataset_id,
                dataset_revision=revision, expires_at=time.time() + 86400,
                rows=rows, summary=summary, **extra)
    count = len(rows) if kind == "groups" else sum(bool(r.get("split")) for r in rows)
    plan["confirmation"] = confirmation or f"确认{'更新采集分组' if kind == 'groups' else '写回训练划分'} {count} 张图片"
    plan["plan_hash"] = digest(plan)
    path = plan_path(plan["plan_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return plan


def load(session: Session, dataset_id: int, plan_id: str, *, fresh: bool = True) -> dict:
    dataset = get_dataset_or_404(session, dataset_id)
    try:
        path = plan_path(plan_id)
        if path.stat().st_size > 40_000_000:
            raise ValueError("oversized")
        plan = json.loads(path.read_text(encoding="utf-8"))
        expected = plan.pop("plan_hash")
        if digest(plan) != expected or plan["dataset_id"] != dataset_id:
            raise ValueError("integrity")
        plan["plan_hash"] = expected
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(409, "预览计划缺失或校验失败，请重新预览。") from exc
    if fresh and (plan["expires_at"] < time.time() or dataset.revision != plan["dataset_revision"]):
        raise HTTPException(409, "预览已过期或数据已变化，请重新预览。")
    return plan


def page(plan: dict, number: int = 1, size: int = 50) -> FrozenPlanRead:
    start = (number - 1) * size
    return FrozenPlanRead(**{k: v for k, v in plan.items() if k != "rows"},
                          total=len(plan["rows"]), page=number, page_size=size,
                          rows=plan["rows"][start:start + size])
