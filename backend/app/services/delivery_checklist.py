"""Explain one real preflight without inventing another qualification policy.

Only the existing planner reads source files and writes its frozen plan. Coverage
describes registered, current human judgments; it never substitutes for the plan.
"""
import re
from collections import defaultdict

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.defect_type import DefectType, SampleDefectLink
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.schemas.delivery_checklist import (
    ChecklistAction, ChecklistCoverage, ChecklistCoverageRow, ChecklistDefectCoverage,
    ChecklistIssue, ChecklistSample, DeliveryChecklistRead, DeliveryChecklistRequest,
)
from app.schemas.validation import ValidationPreviewRequest
from app.services import anomaly_protocol_service as protocol
from app.services import industrial_plan_service as plans, sample_service, validation_plan_service
from app.services.dataset_service import get_dataset_or_404


def _registered_label(sample: Sample, policy_version: int) -> int | None:
    if (sample.file_type != "image" or sample.file_status != "normal"
            or sample.triage_status not in {"ok", "ng"}
            or sample.triaged_file_hash != sample.file_hash
            or sample.triage_policy_version != policy_version):
        return None
    return int(sample.triage_status == "ng")


def _guidance(title: str) -> tuple[ChecklistAction, str]:
    if "范围外" in title:
        return "scope", "检查完整工件及重复内容关联；扩大当前范围，或在方案中明确排除整组，不拆组凑比例。"
    if (any(word in title for word in ("至少", "缺少正常", "缺少异常")) and "组" in title) or "拟合至少需要" in title:
        return "collect", "补充对应正常/异常的独立采集组，再重新检查；不要复制图片补足数量。"
    if any(word in title for word in ("单一对象类别", "CPU", "最多", "官方测试")):
        return "scope", "调整本次范围或整组划分后重新检查；官方测试图片不能进入基线拟合。"
    if any(word in title for word in ("缺少工件", "缺少采集", "分组", "已有划分跨集合", "不能分配")):
        return "groups", "检查工件与批次，按完整隔离组调整；未分组独立采集需由用户明确声明。"
    if any(word in title for word in ("矛盾", "待定", "未分拣", "过期", "临界", "正常等级")):
        return "triage", "逐图核对并保存当前人工判定；仅在本次目标允许时明确排除，模型预测不替代真值。"
    if any(word in title for word in ("原图", "文件", "区域")):
        return "review", "检查原图可访问性、重新扫描变化文件或调整检测区域，再重新预检。"
    if "精确重复" in title:
        return "review", "方案只保留同组的一份内容；原文件不会删除，也不会自动更改人工分组。"
    return "review", "查看涉及图片及本次方案，处理后重新检查；排除项不会自动删除或改判。"


def _issue(
    key: str, title: str, severity: str, sample_ids: list[int], by_id: dict[int, Sample],
    *, count: int | None = None,
) -> ChecklistIssue:
    ids = list(dict.fromkeys(sample_ids))
    action, guidance = _guidance(title)
    return ChecklistIssue(
        key=key, title=title, severity=severity, count=len(ids) if count is None else count,
        sample_ids=ids,
        samples=[ChecklistSample(id=identity, relative_path=by_id[identity].relative_path)
                 for identity in ids[:6] if identity in by_id],
        action=action, guidance=guidance,
    )


def _coverage(
    session: Session, dataset_id: int, selected: list[Sample], groups: dict[str, list[Sample]],
    policy_version: int, independent_capture_declared: bool,
) -> tuple[ChecklistCoverage, list[tuple[str, list[int]]]]:
    selected_ids = {sample.id for sample in selected}
    group_by_sample = {sample.id: gid for gid, members in groups.items() for sample in members}
    labels = {sample.id: _registered_label(sample, policy_version) for sample in selected}
    # Full graph purity matters: a selected normal view is not a normal training
    # group if an unseen member is NG, pending, stale or outside this scope.
    pure_normal = {gid for gid, members in groups.items() if all(
        sample.id in selected_ids and _registered_label(sample, policy_version) == 0
        and sample.ok_grade == "clear" and (sample.capture_group_id or independent_capture_declared)
        for sample in members)}
    valid_abnormal = {gid for gid, members in groups.items() if all(
        sample.id in selected_ids and _registered_label(sample, policy_version) is not None
        and (sample.capture_group_id or independent_capture_declared)
        for sample in members) and any(sample.triage_status == "ng" for sample in members)}

    def axes(attribute: str, names: dict[int, str], unassigned: str) -> list[ChecklistCoverageRow]:
        rows: dict[int | None, list[Sample]] = defaultdict(list)
        for sample in selected:
            if sample.file_type == "image":
                rows[getattr(sample, attribute)].append(sample)
        result = []
        for identity, members in rows.items():
            normal = sum(labels[sample.id] == 0 for sample in members)
            abnormal = sum(labels[sample.id] == 1 for sample in members)
            gids = {group_by_sample[sample.id] for sample in members}
            result.append(ChecklistCoverageRow(
                id=identity, name=names.get(identity, unassigned) if identity is not None else unassigned,
                total=len(members), normal=normal, abnormal=abnormal,
                pending=len(members) - normal - abnormal,
                normal_groups=len(gids & pure_normal), abnormal_groups=len(gids & valid_abnormal),
            ))
        return sorted(result, key=lambda item: (item.id is None, item.name.casefold(), item.id or 0))

    category_names = {row.id: row.name for row in session.exec(select(DatasetCategory).where(
        DatasetCategory.dataset_id == dataset_id)).all()}
    batch_names = {row.id: row.name for row in session.exec(select(DatasetBatch).where(
        DatasetBatch.dataset_id == dataset_id)).all()}
    defect_rows = session.exec(select(DefectType.id, DefectType.name, SampleDefectLink.sample_id)
        .join(SampleDefectLink, SampleDefectLink.defect_type_id == DefectType.id)
        .where(DefectType.dataset_id == dataset_id,
               SampleDefectLink.sample_id.in_(selected_ids)).order_by(DefectType.id, SampleDefectLink.sample_id)).all()
    defects: dict[int, tuple[str, set[int]]] = {}
    for row in defect_rows:
        if labels[row.sample_id] != 1:
            continue
        defects.setdefault(row.id, (row.name, set()))[1].add(row.sample_id)
    defect_coverage = []
    limited = []
    for identity, (name, ids) in defects.items():
        gids = {group_by_sample[sample_id] for sample_id in ids}
        defect_coverage.append(ChecklistDefectCoverage(id=identity, name=name, total=len(ids), groups=len(gids)))
        if len(gids) == 1:
            limited.append((f"缺陷“{name}”只来自 1 个隔离组", sorted(ids)))
    return ChecklistCoverage(
        categories=axes("category_id", category_names, "未分配类别"),
        batches=axes("batch_id", batch_names, "未分配批次"), defects=defect_coverage,
    ), limited


def create_checklist(session: Session, dataset_id: int, request: DeliveryChecklistRequest) -> DeliveryChecklistRead:
    dataset = get_dataset_or_404(session, dataset_id)
    expected_revision = request.protocol.sample_query.expected_dataset_revision
    if expected_revision is not None and expected_revision != dataset.revision:
        raise HTTPException(409, "数据范围版本已变化，请重新读取并检查。")
    all_samples = list(session.exec(select(Sample).where(Sample.dataset_id == dataset_id)
        .order_by(Sample.id).limit(10001)).all())
    if len(all_samples) > 10000:
        raise HTTPException(422, "当前工业协议最多支持 10000 个登记文件，请缩小数据集。")
    by_id = {sample.id: sample for sample in all_samples}
    if request.protocol.sample_query.sample_ids is not None and set(request.protocol.sample_query.sample_ids) - set(by_id):
        raise HTTPException(422, "所选图片不属于当前数据集。")
    query = request.protocol.sample_query.model_dump(exclude={"expected_dataset_revision", "completed_only"})
    selected = sample_service.get_filtered_samples(session, dataset_id, **query)
    if not selected:
        raise HTTPException(422, "当前范围没有图片，请调整范围。")

    # This is the only qualification call. The exact frozen result is returned
    # for the existing export or validation confirmation endpoint to consume.
    if request.target == "training_package":
        plan = protocol.preview(session, dataset_id, request.protocol)
    else:
        plan = validation_plan_service.preview(session, dataset_id, ValidationPreviewRequest(
            mode=request.target, protocol=request.protocol, model=request.model,
            image_size=request.image_size, roi=request.roi,
        ))
    groups = protocol._components(all_samples)
    rows = plan["rows"]
    issues = []
    included = {row["sample_id"] for row in rows if row["split"]}
    training = {row["sample_id"] for row in rows if row["split"] == "train"}
    for index, title in enumerate(plan["summary"]["blockers"]):
        match = re.match(r"(group-\d+)\b", title)
        ids = [sample.id for sample in groups.get(match.group(1), [])] if match else []
        if not ids and "官方测试" in title:
            ids = [sample.id for sample in selected if sample.id in training and sample.official_split == "test"]
        elif not ids and "单一对象类别" in title:
            ids = [sample.id for sample in selected if sample.id in included]
        elif not ids and "缺少工件" in title:
            ids = [sample.id for sample in selected if not sample.capture_group_id]
        elif not ids and "区域检查失败" in title:
            ids = [row["sample_id"] for row in rows if title.startswith(row["relative_path"] + "：")]
        issues.append(_issue(f"blocker-{index}", title, "blocker", ids, by_id))

    excluded: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["exclusion_reason"]:
            excluded[row["exclusion_reason"]].append(row)
    for index, (title, affected) in enumerate(excluded.items()):
        ids = [row["sample_id"] for row in affected]
        if "范围外" in title:
            ids = [sample.id for gid in dict.fromkeys(row["group_id"] for row in affected)
                   for sample in groups[gid]]
        issues.append(_issue(f"excluded-{index}", title, "excluded", ids, by_id, count=len(affected)))

    coverage, limited_defects = _coverage(session, dataset_id, selected, groups,
        dataset.triage_policy_version, request.protocol.independent_capture_declared)
    for index, (title, ids) in enumerate(limited_defects):
        issue = _issue(f"defect-coverage-{index}", title, "notice", ids, by_id)
        issue.action = "collect"
        issue.guidance = "建议补充该缺陷的独立工件或采集批次；这一提示不设通用张数门槛，也不代表模型效果结论。"
        issues.append(issue)
    notes = [
        "验收清单复用本次真实预检。处理或范围变化后需重新检查，原冻结计划不会随当前修改自动更新。",
        "覆盖只统计本次范围内图片的登记态有效人工判断；未分拣、待定、过期及不可用统一列入待确认，不替代原图验收。",
        "正常组为范围完整、登记有效且全员完全 OK 的隔离组；异常组需全组有效且至少有 NG。缺组且未声明独立采集不计候选组，行间组数不可相加；最终资格仍以原图预检和冻结计划为准。",
        "问题的涉及数量按当前范围统计；范围外关联问题的查看清单可能包含完整隔离组成员，计划范围不会自动扩大。",
        "图像级验收不生成像素指标；缺失 Mask 的 NG 图片不会被当作空像素真值。",
    ]
    if request.target == "exploration":
        notes.append("正常一致性探索只检查正常误报与分数分布，没有异常检出率或独立测试结论；无需为此目标补充 NG。")
    return DeliveryChecklistRead(target=request.target, dataset_revision=dataset.revision,
        ready=not plan["summary"]["blocked"], plan=plans.page(plan), issues=issues, coverage=coverage, notes=notes)
