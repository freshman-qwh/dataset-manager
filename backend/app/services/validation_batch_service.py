"""Predict a fresh batch with an unchanged model, ROI, scale and threshold."""
import json
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session, select
from app.models.sample import Sample
from app.models.validation import ValidationDecision, ValidationRun
from app.services import anomaly_protocol_service as protocol, industrial_plan_service as plans
from app.services import validation_run_service as runs
from app.utils.image_validation import image_is_decodable


def preview(session: Session, run_id: str, request) -> dict:
    parent, old, result = runs.load_result(session, run_id)
    if parent.mode == "batch":
        return preview(session, parent.parent_run_id, request)
    decision = session.get(ValidationDecision, parent.id)
    if decision is None:
        raise HTTPException(409, "先在原实验冻结阈值，再验证新批次。")
    model_path = runs.result_root(session, parent) / "model.pt"
    if not model_path.is_file() or protocol.file_digest(model_path) != result["model_sha256"]:
        raise HTTPException(409, "原模型缺失或校验失败，请恢复完整备份。")
    dataset = runs.get_dataset_or_404(session, request.target_dataset_id)
    if dataset.workflow_profile != "industrial_anomaly":
        raise HTTPException(422, "请选择工业异常检测项目。")
    samples = list(session.exec(select(Sample).where(Sample.dataset_id == dataset.id).order_by(Sample.id)).all())
    if len(samples) > 10000:
        raise HTTPException(422, "项目超过 10000 个文件，请按批次建立项目。")
    selected = set(request.sample_ids) if request.sample_ids else {s.id for s in samples}
    if selected - {s.id for s in samples}:
        raise HTTPException(422, "所选图片不属于目标项目。")
    previous = [old]
    # Include previous batches so copying a past evaluation cannot look independent.
    for child in session.exec(select(ValidationRun).where(ValidationRun.parent_run_id == parent.id)).all():
        previous.append(runs.read_contract(child))
    history = [r for contract in previous for r in contract["rows"] if r["split"]]
    hashes = {r["sha256"] for r in history}
    captures = {(r.get("capture_batch_id") or "", r["capture_group_id"]) for r in history if r.get("capture_group_id")}
    rows, blockers = [], []
    for gid, members in protocol._components(samples).items():
        if not any(s.id in selected for s in members):
            continue
        reason = None
        if any(s.id not in selected for s in members):
            reason = "同组存在范围外图片，请纳入整组或排除"
        elif any(s.file_hash in hashes or s.capture_group_id and (s.capture_batch_id or "", s.capture_group_id) in captures for s in members):
            reason = "与原拟合/评估或历史批次内容、采集组重叠，整组排除"
        elif any(not s.capture_group_id for s in members) and not request.independent_capture_declared:
            reason = "缺少采集组，请补充或明确声明独立采集"
            blockers.append(reason)
        checked = []
        labels_by_hash = {}
        for sample in members:
            if sample.id not in selected:
                continue
            label, truth_reason = protocol._eligibility(sample, dataset.triage_policy_version, True)
            try:
                readable = sample.file_type == "image" and sample.file_status == "normal" and image_is_decodable(Path(sample.absolute_path)) and protocol.file_digest(Path(sample.absolute_path)) == sample.file_hash
            except (OSError, ValueError):
                readable = False
            checked.append((sample, label, truth_reason))
            if label is not None:
                labels_by_hash.setdefault(sample.file_hash,set()).add(label)
            if not readable:
                reason = reason or "整组排除：原图不可用或内容变化，请重新扫描"
        if any(len(values)>1 for values in labels_by_hash.values()):
            reason = "整组排除：相同内容的人工判定矛盾，请先复核"
        seen = set()
        for sample, label, truth_reason in checked:
            excluded = reason or ("精确重复，保留首张" if sample.file_hash in seen else None)
            seen.add(sample.file_hash)
            rows.append(dict(sample_id=sample.id, relative_path=sample.relative_path, source_absolute_path=sample.absolute_path,
                sha256=sample.file_hash, group_id=gid, capture_group_id=sample.capture_group_id, capture_batch_id=sample.capture_batch_id,
                label_index=label, triage_status=sample.triage_status, ok_grade=sample.ok_grade, before_split=sample.split,
                split=None if excluded else "batch", exclusion_reason=excluded, truth_notice=truth_reason))
    count = sum(bool(r["split"]) for r in rows)
    if not count or count > 2000:
        blockers.append("新批次需有 1–2000 张不重叠的可用图片。")
    summary = dict(blocked=bool(blockers), blockers=list(dict.fromkeys(blockers)), included_count=count,
        excluded_count=len(rows)-count, unknown_count=sum(bool(r["split"]) and r["label_index"] is None for r in rows),
        parent_name=parent.name, threshold=decision.threshold,
        notice="只复用原模型，不重新拟合或调阈值。重叠采集组/内容已排除；未知真值仅展示预测，不计算误报漏检。")
    return plans.freeze("validation", dataset.id, dataset.revision, rows, summary, mode="batch", recipe=json.loads(parent.recipe_json),
        parent_run_id=parent.id, parent_model_sha256=result["model_sha256"], parent_threshold=decision.threshold,
        triage_policy={"version": dataset.triage_policy_version, "values_json": dataset.triage_policy_json})
