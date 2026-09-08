import hashlib
import json

from sqlmodel import Session

from app.schemas.dataset_snapshot import (
    DatasetSnapshotChangeType,
    DatasetSnapshotDiffItem,
    DatasetSnapshotDiffResponse,
    DatasetSnapshotDiffSummary,
    DatasetSnapshotDocument,
    DatasetSnapshotTrainingLabels,
)
from app.services import dataset_snapshot_service


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sample_map(document: DatasetSnapshotDocument) -> dict[int, dict[str, object]]:
    return {
        int(sample["id"]): sample
        for sample in document.content.samples
        if isinstance(sample.get("id"), int)
    }


def _semantic_annotations(sample: dict[str, object]) -> list[dict[str, object]]:
    values = sample.get("annotations")
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, object]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        normalized.append({key: item for key, item in value.items() if key != "id"})
    return sorted(normalized, key=_canonical_json)


def _projection(sample: dict[str, object] | None) -> dict[str, object] | None:
    if sample is None:
        return None
    annotations = sample.get("annotations")
    return {
        "relative_path": sample.get("relative_path"),
        "file_hash": sample.get("file_hash"),
        "file_status": sample.get("file_status"),
        "split": sample.get("split"),
        "review_status": sample.get("review_status"),
        "annotation_progress": sample.get("annotation_progress"),
        "tags": sample.get("tags") if isinstance(sample.get("tags"), list) else [],
        "annotation_count": len(annotations) if isinstance(annotations, list) else 0,
    }


def _change_types(
    before: dict[str, object],
    after: dict[str, object],
) -> list[DatasetSnapshotChangeType]:
    result: list[DatasetSnapshotChangeType] = []
    file_fields = (
        "filename",
        "relative_path",
        "absolute_path",
        "file_size",
        "extension",
        "file_type",
        "mime_type",
        "file_hash",
        "file_status",
        "file_modified_at",
    )
    metadata_fields = (
        "annotation_progress",
        "review_status",
        "notes",
        "metadata",
    )
    if any(before.get(field) != after.get(field) for field in file_fields):
        result.append("file")
    if any(before.get(field) != after.get(field) for field in metadata_fields):
        result.append("metadata")
    if before.get("tags") != after.get("tags"):
        result.append("tags")
    if before.get("split") != after.get("split"):
        result.append("split")
    if _semantic_annotations(before) != _semantic_annotations(after):
        result.append("annotations")
    return result


def compare_snapshots(
    session: Session,
    dataset_id: int,
    base_snapshot_id: int,
    target_snapshot_id: int,
    *,
    change_type: DatasetSnapshotChangeType | None = None,
    page: int = 1,
    page_size: int = 50,
) -> DatasetSnapshotDiffResponse:
    base = dataset_snapshot_service.read_snapshot_document(
        session, dataset_id, base_snapshot_id
    )
    target = dataset_snapshot_service.read_snapshot_document(
        session, dataset_id, target_snapshot_id
    )
    before_by_id = _sample_map(base)
    after_by_id = _sample_map(target)
    items: list[DatasetSnapshotDiffItem] = []

    for sample_id in sorted(set(before_by_id) | set(after_by_id)):
        before = before_by_id.get(sample_id)
        after = after_by_id.get(sample_id)
        if before is None and after is not None:
            change_types: list[DatasetSnapshotChangeType] = ["added"]
        elif before is not None and after is None:
            change_types = ["removed"]
        elif before is not None and after is not None:
            change_types = _change_types(before, after)
        else:
            continue
        if not change_types:
            continue
        relative_path = str((after or before or {}).get("relative_path") or "")
        items.append(
            DatasetSnapshotDiffItem(
                sample_id=sample_id,
                relative_path=relative_path,
                change_types=change_types,
                before=_projection(before),
                after=_projection(after),
            )
        )

    summary = DatasetSnapshotDiffSummary(
        added=sum("added" in item.change_types for item in items),
        removed=sum("removed" in item.change_types for item in items),
        file_changed=sum("file" in item.change_types for item in items),
        metadata_changed=sum("metadata" in item.change_types for item in items),
        tags_changed=sum("tags" in item.change_types for item in items),
        split_changed=sum("split" in item.change_types for item in items),
        annotations_changed=sum("annotations" in item.change_types for item in items),
        changed_samples=len(items),
    )
    filtered = [item for item in items if change_type is None or change_type in item.change_types]
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 200)
    start = (safe_page - 1) * safe_page_size
    return DatasetSnapshotDiffResponse(
        dataset_id=dataset_id,
        base_snapshot_id=base_snapshot_id,
        target_snapshot_id=target_snapshot_id,
        base_revision=base.dataset_revision,
        target_revision=target.dataset_revision,
        summary=summary,
        total=len(filtered),
        page=safe_page,
        page_size=safe_page_size,
        items=filtered[start : start + safe_page_size],
    )


def rebuild_training_labels(
    session: Session,
    dataset_id: int,
    snapshot_id: int,
) -> DatasetSnapshotTrainingLabels:
    document = dataset_snapshot_service.read_snapshot_document(
        session, dataset_id, snapshot_id
    )
    task_type = str(document.content.dataset.get("task_type") or "")
    include_empty = document.content.export_config.include_empty
    labels: list[dict[str, object]] = []
    for sample in document.content.samples:
        if task_type == "classification":
            sample_labels = sample.get("tags") if isinstance(sample.get("tags"), list) else []
            if not sample_labels and not include_empty:
                continue
            label_payload: object = sample_labels
        else:
            sample_labels = _semantic_annotations(sample)
            if not sample_labels and not include_empty:
                continue
            label_payload = sample_labels
        labels.append(
            {
                "sample_id": sample.get("id"),
                "relative_path": sample.get("relative_path"),
                "file_hash": sample.get("file_hash"),
                "split": sample.get("split"),
                "labels": label_payload,
            }
        )

    hash_payload = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "dataset_revision": document.dataset_revision,
        "format": document.content.export_config.format,
        "include_empty": include_empty,
        "class_map": [item.model_dump(mode="json") for item in document.content.class_map],
        "labels": labels,
    }
    label_sha256 = hashlib.sha256(
        _canonical_json(hash_payload).encode("utf-8")
    ).hexdigest()
    return DatasetSnapshotTrainingLabels(
        schema_version=1,
        snapshot_id=snapshot_id,
        dataset_id=dataset_id,
        dataset_revision=document.dataset_revision,
        snapshot_content_sha256=document.content_sha256,
        format=document.content.export_config.format,
        include_empty=include_empty,
        class_map=document.content.class_map,
        sample_count=len(labels),
        label_sha256=label_sha256,
        labels=labels,
    )
