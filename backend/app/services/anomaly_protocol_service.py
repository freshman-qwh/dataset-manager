"""Image-level anomaly protocols with transitive capture/hash isolation."""
import hashlib
import random
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.models.industrial_receipt import IndustrialReceipt
from app.models.sample import Sample
from app.schemas.industrial import AnomalyPreviewRequest, ConfirmationRead, PlanConfirmation
from app.services import industrial_plan_service as plans, sample_service
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.dataset_service import get_dataset_or_404
from app.utils.image_validation import image_is_decodable


def file_digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _eligibility(sample: Sample, policy: int, borderline: bool) -> tuple[int | None, str | None]:
    if sample.file_type != "image" or sample.file_status != "normal":
        return None, "文件不可用或不是图片"
    if sample.triage_status not in {"ok", "ng"}:
        return None, "未分拣或待定"
    if sample.triaged_file_hash != sample.file_hash or sample.triage_policy_version != policy:
        return None, "判定已过期，需复核"
    if sample.triage_status == "ok" and sample.ok_grade not in {"clear", "borderline"}:
        return None, "统一 OK 尚未确认正常等级"
    if sample.ok_grade == "borderline" and not borderline:
        return None, "临界 OK 默认排除"
    try:
        path = Path(sample.absolute_path)
        if not image_is_decodable(path) or file_digest(path) != sample.file_hash:
            return None, "原图不可解码或内容已变化，请重新扫描并复核"
    except (OSError, ValueError):
        return None, "原图不可读取"
    return int(sample.triage_status == "ng"), None


def _components(samples: list[Sample]) -> dict[str, list[Sample]]:
    parents = {s.id: s.id for s in samples}
    def find(sid):
        while parents[sid] != sid:
            parents[sid] = parents[parents[sid]]
            sid = parents[sid]
        return sid
    keys = {}
    for sample in samples:
        identities = [("hash", sample.file_hash)] if sample.file_hash else []
        if sample.capture_group_id:
            identities.append(("capture", sample.capture_batch_id or "", sample.capture_group_id))
        for identity in identities:
            if identity in keys:
                a, b = find(sample.id), find(keys[identity])
                parents[max(a, b)] = min(a, b)
            else:
                keys[identity] = sample.id
    result = defaultdict(list)
    for sample in samples:
        result[f"group-{find(sample.id)}"].append(sample)
    return dict(result)


def preview(session: Session, dataset_id: int, request: AnomalyPreviewRequest) -> dict:
    dataset = get_dataset_or_404(session, dataset_id)
    if dataset.workflow_profile != "industrial_anomaly":
        raise HTTPException(422, "请先在项目设置中选择工业异常检测用途。")
    # Inspect the full dataset graph even for a selected/current-filter scope.
    all_samples = list(session.exec(select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)).all())
    if len(all_samples) > 10000:
        raise HTTPException(422, "当前试用版每个工业协议支持最多 10000 个登记文件，请按独立采集批次建立项目。")
    query = request.sample_query.model_dump(exclude={"expected_dataset_revision", "completed_only"})
    selected = {s.id for s in sample_service.get_filtered_samples(session, dataset_id, **query)}
    if request.sample_query.sample_ids is not None and set(request.sample_query.sample_ids) - {s.id for s in all_samples}:
        raise HTTPException(422, "所选图片不属于当前项目。")
    if not selected:
        raise HTTPException(422, "当前范围没有图片，请调整范围。")
    components = _components(all_samples)
    if set(request.overrides) - set(components):
        raise HTTPException(422, "调整的组已不存在，请重新预览。")
    labels = {}
    reasons = {}
    blocks = []
    groups = {}
    rows = []
    for gid, members in components.items():
        if not any(s.id in selected for s in members):
            continue
        for s in members:
            labels[s.id], reasons[s.id] = _eligibility(s, dataset.triage_policy_version, request.include_borderline_evaluation)
        hash_labels = defaultdict(set)
        for s in members:
            if labels[s.id] is not None:
                hash_labels[s.file_hash].add(labels[s.id])
        contradictions = any(len(values) > 1 for values in hash_labels.values())
        if contradictions:
            blocks.append(f"{gid} 中相同图片的正常/异常判定矛盾，请先复核。")
        group_reason = None
        if any(s.id not in selected for s in members):
            group_reason = "同组或重复图片存在范围外成员，请扩大范围或排除整组"
        elif any(reasons[s.id] for s in members):
            group_reason = "整组排除：" + next(reasons[s.id] for s in members if reasons[s.id])
        elif contradictions:
            group_reason = "相同内容的判定矛盾"
        elif any(not s.capture_group_id for s in members) and not request.independent_capture_declared and request.overrides.get(gid) != "exclude":
            group_reason = "缺少工件组，尚未声明独立采集"
            blocks.append(f"{gid} 缺少采集分组；补充分组或明确声明未分组图片来自独立采集。")
        if request.overrides.get(gid) == "exclude":
            group_reason = "用户排除整组"
        seen_hashes = set()
        group_rows = []
        for s in members:
            if s.id not in selected:
                continue
            reason = group_reason
            if not reason and s.file_hash in seen_hashes:
                reason = "精确重复，保留同组首张"
            seen_hashes.add(s.file_hash)
            row = dict(sample_id=s.id, relative_path=s.relative_path, source_absolute_path=s.absolute_path,
                       sha256=s.file_hash, group_id=gid, capture_group_id=s.capture_group_id,
                       capture_batch_id=s.capture_batch_id, label_index=labels[s.id],
                       triage_status=s.triage_status, ok_grade=s.ok_grade,
                       before_split=s.split, split=None, exclusion_reason=reason)
            rows.append(row)
            if not reason:
                group_rows.append(row)
        if group_reason or not group_rows:
            continue
        groups[gid] = dict(rows=group_rows,
            pure_normal=all(s.triage_status == "ok" and s.ok_grade == "clear" for s in members),
            existing_splits={s.split for s in members if s.split},
            normal=sum(r["label_index"] == 0 for r in group_rows),
            abnormal=sum(r["label_index"] == 1 for r in group_rows))
    assigned = {}
    for gid, group in groups.items():
        override = request.overrides.get(gid)
        existing = group["existing_splits"]
        if request.preserve_existing and len(existing) > 1 and override is None:
            blocks.append(f"{gid} 的已有划分跨集合，请调整整组。")
        target = override or (next(iter(existing)) if request.preserve_existing and len(existing) == 1 else None)
        if target:
            if target not in {"train", "val", "test"} or target == "train" and not group["pure_normal"]:
                blocks.append(f"{gid} 不能分配到 {target}：训练必须是全员有效完全 OK 的纯正常组。")
            else:
                assigned[gid] = target
    rng = random.Random(request.seed)
    available = sorted(set(groups) - set(assigned))
    rng.shuffle(available)
    def has(split, label):
        return any(assigned.get(gid) == split and group["normal" if label == 0 else "abnormal"] for gid, group in groups.items())
    # Hard coverage first, reserve a pure normal training group before quotas.
    for split, label in (("train", 0), ("val", 1), ("test", 1), ("val", 0), ("test", 0)):
        if has(split, label):
            continue
        candidates = [gid for gid in available if groups[gid]["normal" if label == 0 else "abnormal"] and (split != "train" or groups[gid]["pure_normal"])]
        # Mixed evaluation groups can cover both classes without splitting a part.
        candidates.sort(key=lambda gid: -int(split != "train" and groups[gid]["normal"] > 0 and groups[gid]["abnormal"] > 0))
        if candidates:
            gid = candidates[0]
            assigned[gid] = split
            available.remove(gid)
    normal_total = sum(g["normal"] for g in groups.values())
    abnormal_total = sum(g["abnormal"] for g in groups.values())
    actual = {split: [sum(g["normal"] for k, g in groups.items() if assigned.get(k) == split),
                      sum(g["abnormal"] for k, g in groups.items() if assigned.get(k) == split)]
              for split in ("train", "val", "test")}
    for gid in available:
        group = groups[gid]
        allowed = ("train", "val", "test") if group["pure_normal"] else ("val", "test")
        def deficit(split):
            normal_target = normal_total * request.normal_ratios[("train", "val", "test").index(split)] / 100
            abnormal_target = abnormal_total * (request.abnormal_val_percent if split == "val" else 100 - request.abnormal_val_percent) / 100 if split != "train" else 0
            actual_normal, actual_abnormal = actual[split]
            return (normal_target - actual_normal) * group["normal"] + (abnormal_target - actual_abnormal) * group["abnormal"]
        assigned[gid] = max(allowed, key=deficit)
        actual[assigned[gid]][0] += group["normal"]
        actual[assigned[gid]][1] += group["abnormal"]
    for gid, group in groups.items():
        for row in group["rows"]:
            row["split"] = assigned.get(gid)
    for split, label in (("train", 0), ("val", 0), ("val", 1), ("test", 0), ("test", 1)):
        if not has(split, label):
            blocks.append(f"{split} 缺少{'异常' if label else '正常'}图片的独立组；请补充数据或调整整组。")
    counts = {split: {"normal": sum(r["split"] == split and r["label_index"] == 0 for r in rows),
                      "abnormal": sum(r["split"] == split and r["label_index"] == 1 for r in rows)} for split in ("train", "val", "test")}
    return plans.freeze("anomaly", dataset_id, dataset.revision, rows,
        dict(blocked=bool(blocks), blockers=list(dict.fromkeys(blocks)), counts=counts,
             included_count=sum(bool(r["split"]) for r in rows), excluded_count=sum(not r["split"] for r in rows),
             exclusion_counts=dict(Counter(r["exclusion_reason"] for r in rows if r["exclusion_reason"])),
             group_count=len(groups), full_dataset_checked=len(all_samples),
             notice="图像级协议，无像素掩码。比例为建议；组隔离与正常/异常覆盖优先。默认仅冻结导出计划，现有 split 不变。"),
        config=request.model_dump(mode="json"),
        triage_policy={"version": dataset.triage_policy_version, "values_json": dataset.triage_policy_json})


def validate_plan(session: Session, dataset_id: int, plan_id: str, expected_hash: str) -> dict:
    plan = plans.load(session, dataset_id, plan_id)
    if plan["kind"] != "anomaly" or plan["plan_hash"] != expected_hash or plan["summary"]["blocked"]:
        raise HTTPException(409, "协议未通过检查或计划不匹配，请重新预览。")
    return plan


def confirm_splits(session: Session, dataset_id: int, plan_id: str, request: PlanConfirmation) -> ConfirmationRead:
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    try:
        receipt = session.get(IndustrialReceipt, plan_id)
        if receipt:
            if receipt.dataset_id != dataset_id or receipt.plan_hash != request.plan_hash or receipt.kind != "anomaly":
                raise HTTPException(409, "确认回执不匹配。")
            return ConfirmationRead.model_validate_json(receipt.result_json)
        plan = validate_plan(session, dataset_id, plan_id, request.plan_hash)
        if request.confirmation != plan["confirmation"]:
            raise HTTPException(409, "请输入预览提供的完整确认文字。")
        included = [r for r in plan["rows"] if r["split"]]
        for row in included:
            sample = session.get(Sample, row["sample_id"])
            try:
                same_file = sample is not None and file_digest(Path(sample.absolute_path)) == row["sha256"]
            except OSError:
                same_file = False
            if not same_file:
                raise HTTPException(409, "原图已变化，请重新扫描并预览。")
            sample.split = row["split"]
            session.add(sample)
        revision = bump_dataset_revision(session, dataset_id)
        new_rows = [{**r, "before_split": r["split"] or r["before_split"]} for r in plan["rows"]]
        renewed = plans.freeze("anomaly", dataset_id, revision, new_rows, plan["summary"], config=plan["config"], triage_policy=plan["triage_policy"])
        result = ConfirmationRead(dataset_revision=revision, updated_count=len(included),
                                  plan_id=renewed["plan_id"], plan_hash=renewed["plan_hash"])
        session.add(IndustrialReceipt(plan_id=plan_id, dataset_id=dataset_id, kind="anomaly",
                                      plan_hash=request.plan_hash, result_json=result.model_dump_json()))
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()
