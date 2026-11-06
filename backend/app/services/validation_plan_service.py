"""Freeze exploratory or strict validation inputs before starting the worker."""
import random
from pathlib import Path
from PIL import Image, ImageOps

from fastapi import HTTPException
from sqlmodel import Session, select
from app.models.sample import Sample
from app.schemas.validation import ValidationPreviewRequest
from app.services import anomaly_protocol_service as protocol, industrial_plan_service as plans
from app.services.dataset_service import get_dataset_or_404


def preview(session: Session, dataset_id: int, request: ValidationPreviewRequest) -> dict:
    dataset = get_dataset_or_404(session, dataset_id)
    if dataset.workflow_profile != "industrial_anomaly":
        raise HTTPException(422, "请先选择工业异常检测用途。")
    if request.mode == "evaluation":
        base = protocol.preview(session, dataset_id, request.protocol)
        rows, summary = base["rows"], dict(base["summary"])
    else:
        samples = list(session.exec(select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)).all())
        if len(samples) > 10000:
            raise HTTPException(422, "请按独立批次缩小项目，最多检查 10000 个登记文件。")
        query = request.protocol.sample_query.model_dump(exclude={"expected_dataset_revision", "completed_only"})
        selected = {s.id for s in protocol.sample_service.get_filtered_samples(session, dataset_id, **query)}
        groups = []
        rows = []
        blockers = []
        for gid, members in protocol._components(samples).items():
            if not any(s.id in selected for s in members):
                continue
            reason = None
            if any(s.id not in selected for s in members):
                reason = "同组存在范围外成员"
            elif any(s.triage_status != "ok" or s.ok_grade != "clear" for s in members):
                reason = "正常一致性探索只纳入完全 OK 的纯正常组"
            else:
                for sample in members:
                    _, reason = protocol._eligibility(sample, dataset.triage_policy_version, False)
                    if reason:
                        break
            if not reason and any(not s.capture_group_id for s in members) and not request.protocol.independent_capture_declared:
                reason = "缺少工件组，需补充分组或明确声明独立采集"
                blockers.append(reason)
            seen = set()
            included = []
            for sample in members:
                if sample.id not in selected:
                    continue
                row_reason = reason or ("精确重复，保留同组首张" if sample.file_hash in seen else None)
                seen.add(sample.file_hash)
                row = dict(sample_id=sample.id, relative_path=sample.relative_path, source_absolute_path=sample.absolute_path,
                    sha256=sample.file_hash, label_index=0 if sample.triage_status == "ok" else 1 if sample.triage_status == "ng" else None,
                    group_id=gid, capture_group_id=sample.capture_group_id,
                    capture_batch_id=sample.capture_batch_id, triage_status=sample.triage_status, ok_grade=sample.ok_grade,
                    split=None, exclusion_reason=row_reason, before_split=sample.split)
                rows.append(row)
                if not row_reason:
                    included.append(row)
            if included:
                groups.append(included)
        random.Random(request.protocol.seed).shuffle(groups)
        if len(groups) < 2:
            blockers.append("正常一致性探索至少需要两个独立正常工件组，一个拟合、另一个验证。")
        train_groups = max(1, min(len(groups) - 1, round(len(groups) * 0.8)))
        for index, members in enumerate(groups):
            for row in members:
                row["split"] = "train" if index < train_groups else "val"
        counts = {key: {"normal": sum(r["split"] == key for r in rows), "abnormal": 0} for key in ("train", "val", "test")}
        summary = dict(blocked=bool(blockers), blockers=blockers, counts=counts,
            included_count=sum(bool(r["split"]) for r in rows), excluded_count=sum(not r["split"] for r in rows),
            full_dataset_checked=len(samples), group_count=len(groups),
            notice="正常一致性探索：只评价已知正常的误报与分数分布，没有异常检出率或独立测试结论。")
    blockers = list(summary["blockers"])
    included_ids = [row["sample_id"] for row in rows if row["split"]]
    if included_ids:
        categories = set(session.exec(select(Sample.category_id).where(
            Sample.dataset_id == dataset_id, Sample.id.in_(included_ids),
            Sample.category_id.is_not(None),
        )).all())
        if len(categories) > 1:
            blockers.append("当前基线按单一对象类别拟合，请筛选一个类别后创建实验。")
        official_test_ids = set(session.exec(select(Sample.id).where(
            Sample.dataset_id == dataset_id, Sample.id.in_(included_ids),
            Sample.official_split == "test",
        )).all())
        if any(row["sample_id"] in official_test_ids and row["split"] == "train" for row in rows):
            blockers.append("官方测试图片不能用于拟合，请保留官方测试范围并显式准备独立验证集。")
    if request.roi:
        from app.services.validation_preparation_service import crop_box
        for row in rows:
            if not row["split"]:
                continue
            try:
                with Image.open(row["source_absolute_path"]) as image:
                    crop_box(ImageOps.exif_transpose(image).size, request.roi)
            except (OSError, ValueError) as exc:
                blockers.append(f"{row['relative_path']}：区域检查失败，{exc}")
    if sum(r["split"] == "train" for r in rows) < 2:
        blockers.append("拟合至少需要 2 张有效正常图片。")
    if sum(r["split"] == "train" for r in rows) > 256 or sum(bool(r["split"]) for r in rows) > 2000:
        blockers.append("CPU 快速验证单次最多 256 张拟合图片、2000 张总图片，请在当前筛选或所选范围缩小后重试。")
    recipe = dict(model=request.model, image_size=request.image_size,
        roi=request.roi.model_dump() if request.roi else None,
        backbone="resnet18", weights="torchvision-imagenet1k-v1-f37072fd", adapter_version=1,
        normalization="imagenet-rgb", exif_transpose=True, seed=42, device="cpu")
    summary.update(blockers=list(dict.fromkeys(blockers)), blocked=bool(blockers), mode=request.mode)
    return plans.freeze("validation", dataset_id, dataset.revision, rows, summary,
        recipe=recipe, mode=request.mode, triage_policy={"version": dataset.triage_policy_version, "values_json": dataset.triage_policy_json})


def validate(session: Session, dataset_id: int, plan_id: str, plan_hash: str) -> dict:
    plan = plans.load(session, dataset_id, plan_id)
    if plan["kind"] != "validation" or plan["plan_hash"] != plan_hash or plan["summary"]["blocked"]:
        raise HTTPException(409, "预览未通过或计划不匹配，请重新检查。")
    return plan
