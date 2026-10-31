"""Image-level metrics and immutable test decisions; never rewrite human truth."""
import json
import math
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select
from app.models.sample import Sample
from app.models.validation import ValidationDecision, ValidationTestExposure
from app.services import validation_run_service as runs


def metrics(rows: list[dict], threshold: float) -> dict:
    known = [r for r in rows if r.get("label_index") in (0, 1)]
    tp = sum(r["label_index"] == 1 and r["score"] >= threshold for r in known)
    fp = sum(r["label_index"] == 0 and r["score"] >= threshold for r in known)
    fn = sum(r["label_index"] == 1 and r["score"] < threshold for r in known)
    tn = sum(r["label_index"] == 0 and r["score"] < threshold for r in known)
    normal, abnormal = fp + tn, tp + fn
    auc = None
    if normal and abnormal:
        grouped = defaultdict(list)
        for row in known:
            grouped[row["score"]].append(row["label_index"])
        rank, positive_rank = 1, 0.0
        for score in sorted(grouped):
            labels = grouped[score]
            positive_rank += sum(labels) * (rank + (len(labels) - 1) / 2)
            rank += len(labels)
        auc = (positive_rank - abnormal * (abnormal + 1) / 2) / (normal * abnormal)
    return dict(total=len(rows), known=len(known), unknown=len(rows)-len(known), normal=normal, abnormal=abnormal,
        true_positive=tp, false_positive=fp, false_negative=fn, true_negative=tn,
        false_positive_rate=fp / normal if normal else None,
        recall=tp / abnormal if abnormal else None,
        precision=tp / (tp + fp) if tp + fp else None,
        f1=2 * tp / (2 * tp + fp + fn) if abnormal else None, auroc=auc)


def joined_rows(contract: dict, result: dict) -> list[dict]:
    scores = {int(r["sample_id"]): float(r["score"]) for r in result["predictions"]}
    return [{k: v for k, v in row.items() if k != "source_absolute_path"} | {"score": scores[row["sample_id"]]}
            for row in contract["rows"] if row["split"]]


def recommended_threshold(rows: list[dict]) -> tuple[float, str]:
    validation = [r for r in rows if r["split"] == "val"]
    if not validation:
        raise HTTPException(409, "没有可用于选择阈值的独立验证图片。")
    scores = sorted(r["score"] for r in validation)
    if {r["label_index"] for r in validation} == {0, 1}:
        candidates = sorted(set(scores)) + [math.nextafter(scores[-1], math.inf)]
        def quality(value):
            tp = sum(r["label_index"] == 1 and r["score"] >= value for r in validation)
            fp = sum(r["label_index"] == 0 and r["score"] >= value for r in validation)
            fn = sum(r["label_index"] == 1 and r["score"] < value for r in validation)
            return 2 * tp / (2 * tp + fp + fn), -fp, value
        threshold = max(candidates, key=quality)
        return threshold, "验证集图像 F1 推荐值，未使用测试分数选择"
    normal = sorted(r["score"] for r in validation if r["label_index"] == 0)
    if not normal:
        raise HTTPException(409, "验证集没有已确认正常图片，无法建立正常一致性阈值。")
    return math.nextafter(normal[max(0, math.ceil(len(normal) * 0.99) - 1)], math.inf), "正常验证分数 99% 经验分位，小样本时接近最大值"


def effective_threshold(session: Session, run, rows: list[dict], supplied: float | None) -> tuple[float, str]:
    if run.mode == "batch":
        parent = session.get(ValidationDecision, run.parent_run_id)
        if not parent:
            raise HTTPException(409, "原实验尚未冻结阈值。")
        if supplied is not None and not math.isclose(supplied, parent.threshold, rel_tol=1e-12, abs_tol=1e-12):
            raise HTTPException(422, "第二批固定使用原模型的冻结阈值。")
        return parent.threshold, "沿用原实验冻结阈值，未在新批次重新调参"
    if supplied is not None:
        if not math.isfinite(supplied):
            raise HTTPException(422, "阈值必须为有限数值。")
        return supplied, "当前验证集交互预览，未修改冻结评估"
    decision = session.get(ValidationDecision, run.id)
    if decision:
        return decision.threshold, "本实验已冻结阈值"
    return recommended_threshold(rows)


def overview(session: Session, run_id: str, threshold: float | None = None) -> dict:
    run, contract, result = runs.load_result(session, run_id)
    rows = joined_rows(contract, result)
    value, source = effective_threshold(session, run, rows, threshold)
    decision = session.get(ValidationDecision, run.id)
    validation = [r for r in rows if r["split"] == ("batch" if run.mode == "batch" else "val")]
    values = [r["score"] for r in validation]
    low, high = min(values, default=value), max(values, default=value)
    span = max(high - low, abs(value) * 0.05, 1e-6)
    reference = next((r["sample_id"] for r in rows if r["split"] == "train" and r["label_index"] == 0), None)
    bins = []
    for index in range(12):
        left, right = low + index * span / 12, low + (index + 1) * span / 12
        selected = [r for r in validation if left <= r["score"] and (r["score"] < right or index == 11)]
        bins.append(dict(left=left, right=right, normal=sum(r["label_index"] == 0 for r in selected), abnormal=sum(r["label_index"] == 1 for r in selected), unknown=sum(r["label_index"] is None for r in selected)))
    report = json.loads(decision.report_json) if decision else None
    return dict(run=runs.read_run(session, run).model_dump(mode="json"), threshold=value, threshold_source=source,
        threshold_range={"min": min(low - span * 0.05, value), "max": max(high + span * 0.05, value)},
        validation_metrics=metrics(validation, value), frozen_decision=report,
        test_locked=run.mode == "evaluation" and decision is None,
        reference_sample_id=reference, map_scale=result["map_scale"], histogram=bins,
        total_seconds=result["total_seconds"], fit_seconds=result["fit_seconds"],
        notes=["异常分数不是置信概率；热图采用本次验证集的统一强度标尺。", "没有像素真值，本页不计算像素级指标。"] +
              (["当前项目版本已变化，本页仍保留运行当时的图片和人工判定。"] if run.dataset_revision != runs.get_dataset_or_404(session, run.dataset_id).revision else []))


def freeze_decision(session: Session, run_id: str, threshold: float) -> dict:
    if not math.isfinite(threshold):
        raise HTTPException(422, "阈值必须为有限数值。")
    run, contract, result = runs.load_result(session, run_id)
    if run.mode == "batch":
        raise HTTPException(409, "第二批固定沿用原模型阈值。")
    rows = joined_rows(contract, result)
    session.commit(); session.exec(text("BEGIN IMMEDIATE"))
    try:
        existing = session.get(ValidationDecision, run_id)
        if existing:
            if existing.threshold != threshold:
                raise HTTPException(409, "本实验已有冻结结果。滑块仍可预览验证集；新评估请新建实验保留历史。")
            report = json.loads(existing.report_json); session.commit(); return report
        testing = [r for r in rows if r["split"] == "test"]
        hashes = {r["sha256"] for r in testing}
        seen = list(session.exec(select(ValidationTestExposure).where(ValidationTestExposure.sha256.in_(hashes))).all()) if hashes else []
        report = dict(threshold=threshold, validation=metrics([r for r in rows if r["split"] == "val"], threshold),
            test=metrics(testing, threshold) if testing else None,
            reused_test_hashes=len(seen), independent_test=bool(testing) and not seen,
            note="测试图片已在其他实验查看过，当前作为开发对照；独立结论请留新批次。" if seen else "阈值仅由验证集确定，本次首次在应用中开启这些测试图片。" if testing else "正常一致性探索，没有独立测试结论。")
        session.add(ValidationDecision(run_id=run_id, threshold=threshold, report_json=json.dumps(report)))
        for digest in hashes - {item.sha256 for item in seen}:
            session.add(ValidationTestExposure(sha256=digest, first_run_id=run_id))
        session.commit()
        return report
    except Exception:
        session.rollback(); raise


def rows_page(session: Session, run_id: str, *, split: str = "val", category: str = "all",
              threshold: float | None = None, page: int = 1, page_size: int = 30) -> dict:
    run, contract, result = runs.load_result(session, run_id)
    rows = joined_rows(contract, result)
    value, _ = effective_threshold(session, run, rows, threshold)
    decision = session.get(ValidationDecision, run_id)
    if split == "test":
        if not decision:
            raise HTTPException(409, "先在验证集冻结阈值，再开启测试结果。")
        if threshold is not None and threshold != decision.threshold:
            raise HTTPException(422, "测试集只显示已冻结阈值的结果。")
        value = decision.threshold
    selected = []
    visible_scores = [r["score"] for r in rows if r["split"] == split]
    score_span = max((max(visible_scores) - min(visible_scores)) * 0.05, 1e-8) if visible_scores else 1e-8
    for row in rows:
        if row["split"] != split:
            continue
        predicted = int(row["score"] >= value)
        label = row["label_index"]
        outcome = "unknown" if label is None else "false_positive" if predicted and label == 0 else "false_negative" if not predicted and label == 1 else "correct_abnormal" if label == 1 else "correct_normal"
        matches_truth = category == "truth_normal" and label == 0 or category == "truth_abnormal" and label == 1
        if category != "all" and category != outcome and not matches_truth and not (category == "near_threshold" and abs(row["score"] - value) <= score_span):
            continue
        selected.append({**row, "predicted_label": predicted, "category": outcome})
    selected.sort(key=lambda r: abs(r["score"] - value) if category == "near_threshold" else -r["score"])
    start = (page - 1) * page_size
    items = selected[start:start + page_size]
    current = {s.id: s for s in session.exec(select(Sample).where(Sample.id.in_([r["sample_id"] for r in items]))).all()} if items else {}
    for row in items:
        sample = current.get(row["sample_id"])
        row["judgment_changed"] = (sample is None or sample.file_hash != row["sha256"] or sample.triage_status != row["triage_status"] or sample.ok_grade != row["ok_grade"] or sample.triage_policy_version != contract["triage_policy"]["version"])
        row["current_sample_available"] = sample is not None and sample.file_hash == row["sha256"]
    return dict(items=items, total=len(selected), page=page, page_size=page_size, threshold=value)


def image_path(session: Session, run_id: str, sample_id: int, kind: str):
    run = runs.get_run(session, run_id)
    row = next((r for r in runs.read_contract(run)["rows"] if r["sample_id"] == sample_id and r["split"]), None)
    if row is None:
        raise HTTPException(404, "图片不在此实验中。")
    if row["split"] == "test" and session.get(ValidationDecision, run_id) is None:
        raise HTTPException(409, "测试结果尚未开启。")
    root = runs.result_root(session, run)
    path = root / ("heatmaps" if kind == "heatmap" else "previews") / f"{sample_id}.{'png' if kind == 'heatmap' else 'jpg'}"
    if not path.is_file():
        raise HTTPException(410, "结果图片缺失，请恢复完整备份。")
    return path
