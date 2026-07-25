import json
from collections import Counter
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.workflow import TASK_CAPABILITIES
from app.models.dataset import utc_now
from app.models.sample import Sample
from app.models.training_readiness_state import TrainingReadinessState
from app.schemas.annotation_export import AnnotationClassMapItem, AnnotationExportSampleQuery
from app.schemas.training_readiness import (
    TrainingReadinessConfig,
    TrainingReadinessConfigRequest,
    TrainingReadinessReport,
)
from app.services import dataset_service, quality_service


EXPORT_FORMATS_BY_TASK: dict[str, tuple[list[str], list[str]]] = {
    "detection": (
        ["coco_detection", "yolo_detection", "voc"],
        ["labelme", "coco_segmentation", "yolo_segmentation"],
    ),
    "segmentation": (
        ["coco_segmentation", "yolo_segmentation", "labelme"],
        ["coco_detection", "yolo_detection", "voc"],
    ),
    "classification": (
        ["csv"],
        ["manifest"],
    ),
}


class TrainingReadinessConfigError(ValueError):
    pass


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_config(
    session: Session,
    dataset_id: int,
    task_type: str,
    payload: TrainingReadinessConfigRequest,
) -> None:
    compatible_formats, advanced_formats = EXPORT_FORMATS_BY_TASK.get(
        task_type,
        (["manifest"], []),
    )
    if payload.format not in {*compatible_formats, *advanced_formats}:
        raise TrainingReadinessConfigError(
            f"Export format '{payload.format}' is not available for task type '{task_type}'."
        )
    if payload.scope == "split" and not payload.split:
        raise TrainingReadinessConfigError("A split is required for split-scoped exports.")
    if payload.scope == "selected" and not payload.sample_query.sample_ids:
        raise TrainingReadinessConfigError(
            "At least one sample is required for selected-scoped exports."
        )
    if payload.scope == "selected":
        requested_ids = set(payload.sample_query.sample_ids or [])
        available_ids = set(
            session.exec(
                select(Sample.id).where(
                    Sample.dataset_id == dataset_id,
                    Sample.id.in_(requested_ids),
                )
            ).all()
        )
        if requested_ids != available_ids:
            raise TrainingReadinessConfigError(
                "Selected samples must all belong to the target dataset."
            )


def _normalized_sample_query(
    payload: TrainingReadinessConfigRequest,
) -> AnnotationExportSampleQuery:
    sort_by = payload.sample_query.sort_by
    sort_order = payload.sample_query.sort_order
    if payload.scope == "all":
        return AnnotationExportSampleQuery(sort_by=sort_by, sort_order=sort_order)
    if payload.scope == "split":
        return AnnotationExportSampleQuery(
            split=payload.split,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    if payload.scope == "selected":
        return AnnotationExportSampleQuery(
            sample_ids=payload.sample_query.sample_ids,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    return payload.sample_query


def _state_to_config(
    state: TrainingReadinessState,
) -> TrainingReadinessConfig | None:
    try:
        sample_query = AnnotationExportSampleQuery.model_validate_json(
            state.sample_query_json
        )
        class_map = [
            AnnotationClassMapItem.model_validate(item)
            for item in json.loads(state.class_map_json)
        ]
        return TrainingReadinessConfig(
            task_type=state.task_type,
            format=state.export_format,
            scope=state.scope,
            split=state.split,
            include_empty=state.include_empty,
            sample_query=sample_query,
            class_map=class_map,
            saved_at=_as_utc(state.saved_at),
            last_export_at=_as_utc(state.last_export_at),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        # A stale or manually modified state row must not make the readiness report unusable.
        return None


def _get_state(
    session: Session,
    dataset_id: int,
) -> TrainingReadinessState | None:
    return session.exec(
        select(TrainingReadinessState).where(
            TrainingReadinessState.dataset_id == dataset_id
        )
    ).first()


def _save_state(
    session: Session,
    dataset_id: int,
    payload: TrainingReadinessConfigRequest,
    *,
    mark_exported: bool,
) -> TrainingReadinessConfig:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    _validate_config(session, dataset_id, dataset.task_type, payload)
    state = _get_state(session, dataset_id)
    if state is None:
        state = TrainingReadinessState(
            dataset_id=dataset_id,
            task_type=dataset.task_type,
            export_format=payload.format,
            scope=payload.scope,
        )

    saved_at = utc_now()
    state.task_type = dataset.task_type
    state.export_format = payload.format
    state.scope = payload.scope
    state.split = payload.split if payload.scope == "split" else None
    state.include_empty = payload.include_empty
    state.sample_query_json = _normalized_sample_query(payload).model_dump_json()
    state.class_map_json = json.dumps(
        [item.model_dump(mode="json") for item in payload.class_map],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    state.saved_at = saved_at
    if mark_exported:
        state.last_export_at = saved_at
    session.add(state)
    session.commit()
    session.refresh(state)
    config = _state_to_config(state)
    if config is None:
        raise RuntimeError("Saved training readiness state could not be decoded.")
    return config


def save_training_readiness_config(
    session: Session,
    dataset_id: int,
    payload: TrainingReadinessConfigRequest,
) -> TrainingReadinessConfig:
    return _save_state(
        session,
        dataset_id,
        payload,
        mark_exported=False,
    )


def record_training_export(
    session: Session,
    dataset_id: int,
    payload: TrainingReadinessConfigRequest,
) -> TrainingReadinessConfig:
    return _save_state(
        session,
        dataset_id,
        payload,
        mark_exported=True,
    )


def build_training_readiness_report(
    session: Session,
    dataset_id: int,
) -> TrainingReadinessReport:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    quality = quality_service.build_quality_report(session, dataset_id)
    samples = session.exec(
        select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.id)
    ).all()
    scoped_samples = (
        samples
        if dataset.task_type == "classification"
        else [sample for sample in samples if sample.file_type == "image"]
    )

    split_counts = Counter(
        (sample.split or "unassigned").strip() or "unassigned"
        for sample in scoped_samples
    )
    split_covered_sample_count = len(scoped_samples) - split_counts["unassigned"]
    split_coverage_percent = (
        round(split_covered_sample_count / len(scoped_samples) * 100, 1)
        if scoped_samples
        else 0.0
    )

    completed_sample_count = (
        quality.samples_with_objects_count
        if dataset.task_type == "classification"
        else (
            quality.annotation_progress_counts.get("completed_with_objects", 0)
            + quality.confirmed_empty_sample_count
        )
    )
    pending_sample_count = max(len(scoped_samples) - completed_sample_count, 0)
    pending_review_count = quality.review_status_counts.get("in_review", 0)
    rejected_sample_count = quality.review_status_counts.get("rejected", 0)

    capabilities = TASK_CAPABILITIES.get(dataset.task_type)
    if capabilities is None or quality.error_count > 0:
        readiness_status = "blocked"
    elif (
        pending_sample_count > 0
        or pending_review_count > 0
        or rejected_sample_count > 0
        or split_counts["unassigned"] > 0
        or quality.warning_count > 0
    ):
        readiness_status = "needs_attention"
    else:
        readiness_status = "ready"

    compatible_formats, advanced_formats = EXPORT_FORMATS_BY_TASK.get(
        dataset.task_type,
        (["manifest"], []),
    )
    default_format = (
        str(capabilities["default_export_format"])
        if capabilities is not None
        else "manifest"
    )
    task_label = (
        str(capabilities["label"])
        if capabilities is not None
        else f"旧任务类型：{dataset.task_type}"
    )
    state = _get_state(session, dataset_id)
    last_config = _state_to_config(state) if state is not None else None

    return TrainingReadinessReport(
        dataset_id=dataset_id,
        generated_at=quality.generated_at,
        task_type=dataset.task_type,
        task_label=task_label,
        status=readiness_status,
        recommended_export_format=default_format,
        compatible_export_formats=compatible_formats,
        advanced_export_formats=advanced_formats,
        scoped_sample_count=len(scoped_samples),
        completed_sample_count=completed_sample_count,
        confirmed_empty_sample_count=quality.confirmed_empty_sample_count,
        pending_sample_count=pending_sample_count,
        pending_review_count=pending_review_count,
        rejected_sample_count=rejected_sample_count,
        blocking_issue_count=quality.error_count,
        suggested_fix_count=quality.warning_count,
        notice_count=quality.info_count,
        truncated_issue_count=quality.truncated_issue_count,
        issues=quality.issues,
        split_counts=dict(sorted(split_counts.items())),
        split_covered_sample_count=split_covered_sample_count,
        split_coverage_percent=split_coverage_percent,
        last_export_at=_as_utc(state.last_export_at) if state is not None else None,
        last_config=last_config,
    )
