import csv
import io
import json
from pathlib import PurePosixPath

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.models.industrial_receipt import IndustrialReceipt
from app.models.organization import DatasetBatch
from app.models.sample import Sample
from app.schemas.industrial import ConfirmationRead, GroupPreviewRequest, PlanConfirmation
from app.services import industrial_plan_service as plans
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.dataset_service import get_dataset_or_404


def preview(session: Session, dataset_id: int, request: GroupPreviewRequest) -> dict:
    dataset = get_dataset_or_404(session, dataset_id)
    samples = list(session.exec(select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)).all())
    mapping: dict[int, tuple[str | None, str | None]] = {}
    by_path = {s.relative_path.replace("\\", "/"): s for s in samples}
    path_counts: dict[str, int] = {}
    for sample in samples:
        path = sample.relative_path.replace("\\", "/")
        path_counts[path] = path_counts.get(path, 0) + 1
    if request.mode == "selected":
        ids = set(request.sample_ids)
        if not ids or ids - {s.id for s in samples}:
            raise HTTPException(422, "请选择当前项目的图片（最多 200 张）。")
        mapping = {sid: (request.capture_group_id, request.capture_batch_id) for sid in ids}
    elif request.mode == "directories":
        for s in samples:
            parent = str(PurePosixPath(s.relative_path.replace("\\", "/")).parent)
            if parent == ".":
                raise HTTPException(422, "根目录存在图片，无法据此推断工件。请用所选图片或映射表明确分组。")
            if len(parent) > 160:
                raise HTTPException(422, "目录名称超过 160 字符，请使用映射表。")
            mapping[s.id] = (parent, request.capture_batch_id)
    elif request.mode == "filename":
        rule = request.filename_rule
        for sample in samples:
            path = PurePosixPath(sample.relative_path.replace("\\", "/"))
            parts = path.stem.split(rule.delimiter)
            if len(parts) <= rule.keep_segments or any(not value for value in parts):
                raise HTTPException(422, f"文件名 {path.name} 无法按当前规则去除视角后缀，请调整保留段数或使用映射表。")
            group = rule.delimiter.join(parts[:rule.keep_segments])
            if rule.include_parent and str(path.parent) != ".":
                group = f"{path.parent}/{group}"
            if len(group) > 160:
                raise HTTPException(422, "提取后的工件编号超过 160 字符，请使用映射表。")
            mapping[sample.id] = (group, request.capture_batch_id)
    else:
        try:
            source = (request.mapping_text or "").lstrip("\ufeff \r\n")
            values = json.loads(source) if source.startswith("[") else list(csv.DictReader(io.StringIO(source)))
            if not isinstance(values, list) or not values or len(values) > 10000:
                raise ValueError("empty or oversized")
            for item in values:
                path = str(item[request.path_column]).replace("\\", "/")
                if path_counts.get(path, 0) > 1:
                    raise ValueError(f"相对路径对应多个来源，请改用所选图片设置工件与批次：{path}")
                sample = by_path.get(path)
                if sample is None or sample.id in mapping:
                    raise ValueError(f"路径不匹配或重复：{path}")
                group = str(item[request.group_column] or "").strip() or None
                batch = str(item.get(request.batch_column) or "").strip() or None
                if any(v is not None and len(v) > 160 for v in (group, batch)):
                    raise ValueError("工件/批次最多 160 字符")
                mapping[sample.id] = (group, batch)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise HTTPException(422, f"映射表无效：{exc}") from exc
    rows = [dict(sample_id=s.id, relative_path=s.relative_path, file_hash=s.file_hash,
                 before_group=s.capture_group_id, before_batch=s.capture_batch_id,
                 capture_group_id=mapping[s.id][0], capture_batch_id=mapping[s.id][1], split=s.split)
            for s in samples if s.id in mapping]
    if not rows:
        raise HTTPException(422, "没有可更新图片。")
    return plans.freeze("groups", dataset_id, dataset.revision, rows,
                        dict(sample_count=len(rows), existing_split_count=sum(bool(r["split"]) for r in rows),
                             group_count=len(set(mapping.values())),
                             notice="仅更新分组元数据；已有 split 不变，训练准备时会重新检查整组隔离。目录草稿需确认同目录确属同一工件。"),
                        filename_rule=request.filename_rule.model_dump() if request.mode == "filename" and request.remember_rule else None)


def confirm(session: Session, dataset_id: int, plan_id: str, request: PlanConfirmation) -> ConfirmationRead:
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    try:
        receipt = session.get(IndustrialReceipt, plan_id)
        if receipt:
            if receipt.dataset_id != dataset_id or receipt.plan_hash != request.plan_hash or receipt.kind != "groups":
                raise HTTPException(409, "确认回执不匹配。")
            return ConfirmationRead.model_validate_json(receipt.result_json)
        plan = plans.load(session, dataset_id, plan_id)
        if plan["kind"] != "groups" or request.plan_hash != plan["plan_hash"] or request.confirmation != plan["confirmation"]:
            raise HTTPException(409, "确认内容与预览不一致。")
        for row in plan["rows"]:
            sample = session.get(Sample, row["sample_id"])
            if sample is None or sample.dataset_id != dataset_id or sample.file_hash != row["file_hash"]:
                raise HTTPException(409, "图片已变化，请重新预览。")
            sample.capture_group_id = row["capture_group_id"]
            sample.capture_batch_id = row["capture_batch_id"]
            # The legacy group editor accepts a batch code. Keep its stable
            # organization relation in sync without altering the grouping rule.
            if sample.capture_batch_id:
                batch = session.exec(select(DatasetBatch).where(
                    DatasetBatch.dataset_id == dataset_id,
                    DatasetBatch.code == sample.capture_batch_id,
                )).first()
                if batch is None:
                    batch = DatasetBatch(dataset_id=dataset_id, name=sample.capture_batch_id, code=sample.capture_batch_id)
                    session.add(batch)
                    session.flush()
                sample.batch_id = batch.id
            else:
                sample.batch_id = None
            session.add(sample)
        if plan.get("filename_rule"):
            dataset = get_dataset_or_404(session, dataset_id)
            settings = json.loads(dataset.industrial_settings_json or "{}")
            settings["filename_group_rule"] = plan["filename_rule"]
            dataset.industrial_settings_json = json.dumps(settings)
            session.add(dataset)
        bump_dataset_revision(session, dataset_id)
        session.flush()
        session.expire_all()
        result = ConfirmationRead(dataset_revision=get_dataset_or_404(session, dataset_id).revision,
                                  updated_count=len(plan["rows"]))
        session.add(IndustrialReceipt(plan_id=plan_id, dataset_id=dataset_id, kind="groups",
                                      plan_hash=plan["plan_hash"], result_json=result.model_dump_json()))
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        # Also ends the transaction on the receipt-only retry path.
        session.rollback()
