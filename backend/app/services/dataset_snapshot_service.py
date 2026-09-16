import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.annotation_class import AnnotationClass
from app.models.dataset import Dataset, utc_now
from app.models.dataset_snapshot import DatasetSnapshot
from app.models.tag import Tag
from app.schemas.annotation_export import AnnotationClassMapItem
from app.schemas.dataset_snapshot import (
    DatasetSnapshotContent,
    DatasetSnapshotCreate,
    DatasetSnapshotDocument,
    DatasetSnapshotExportConfig,
    DatasetSnapshotRead,
)
from app.services import annotation_service, sample_service
from app.services.dataset_service import get_dataset_or_404


class DatasetSnapshotError(RuntimeError):
    pass


class DatasetSnapshotSchemaUnavailableError(DatasetSnapshotError):
    pass


class DatasetSnapshotStaleError(DatasetSnapshotError):
    pass


class DatasetSnapshotArtifactError(DatasetSnapshotError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json_dict(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_list(value: str | None) -> list[object]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _snapshot_root() -> Path:
    return (get_settings().storage_root / "snapshots").resolve()


def _artifact_path(relative_path: str) -> Path:
    root = _snapshot_root()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise DatasetSnapshotArtifactError("Snapshot artifact path is outside application storage.")
    return candidate


def _read_model(snapshot: DatasetSnapshot) -> DatasetSnapshotRead:
    return DatasetSnapshotRead(
        id=snapshot.id or 0,
        dataset_id=snapshot.dataset_id,
        dataset_revision=snapshot.dataset_revision,
        name=snapshot.name,
        content_sha256=snapshot.content_sha256,
        sample_count=snapshot.sample_count,
        annotation_count=snapshot.annotation_count,
        class_count=snapshot.class_count,
        sample_query=json.loads(snapshot.query_json),
        export_config=json.loads(snapshot.export_config_json),
        created_at=snapshot.created_at,
    )


def _derived_class_map(labels: set[str]) -> list[AnnotationClassMapItem]:
    return [
        AnnotationClassMapItem(name=name, id=index, coco_id=index + 1, yolo_id=index)
        for index, name in enumerate(sorted(label.strip() for label in labels if label.strip()))
    ]


def _build_snapshot_content(
    session: Session,
    dataset: Dataset,
    payload: DatasetSnapshotCreate,
) -> DatasetSnapshotContent:
    query = payload.sample_query
    samples = sample_service.get_filtered_samples(
        session,
        dataset.id or 0,
        search=query.search,
        file_type=query.file_type,
        file_status=query.file_status,
        tag=query.tag,
        split=query.split,
        review_status=query.review_status,
        annotation_progress=query.annotation_progress,
        sample_ids=query.sample_ids,
        sort_by=query.sort_by,
        sort_order=query.sort_order,
    )
    sample_ids = [sample.id for sample in samples if sample.id is not None]
    annotations_by_sample = annotation_service.annotations_by_sample(session, sample_ids)
    tags = list(
        session.exec(
            select(Tag).where(Tag.dataset_id == dataset.id).order_by(Tag.name, Tag.id)
        ).all()
    )
    annotation_classes = list(
        session.exec(
            select(AnnotationClass)
            .where(AnnotationClass.dataset_id == dataset.id)
            .order_by(AnnotationClass.name, AnnotationClass.id)
        ).all()
    )

    if dataset.task_type == "classification":
        labels = {tag.name for sample in samples for tag in sample.tags}
    else:
        labels = {
            annotation.label
            for values in annotations_by_sample.values()
            for annotation in values
        }
    class_map = payload.export_config.class_map or _derived_class_map(labels)
    export_config = DatasetSnapshotExportConfig(
        format=payload.export_config.format,
        include_empty=payload.export_config.include_empty,
        class_map=class_map,
    )

    snapshot_samples: list[dict[str, object]] = []
    annotation_count = 0
    for sample in samples:
        sample_annotations = annotations_by_sample.get(sample.id or 0, [])
        annotation_count += len(sample_annotations)
        snapshot_samples.append(
            {
                "id": sample.id,
                "filename": sample.filename,
                "relative_path": sample.relative_path,
                "absolute_path": sample.absolute_path,
                "file_size": sample.file_size,
                "extension": sample.extension,
                "file_type": sample.file_type,
                "mime_type": sample.mime_type,
                "file_hash": sample.file_hash,
                "file_status": sample.file_status,
                "file_modified_at": (
                    sample.file_modified_at.isoformat() if sample.file_modified_at else None
                ),
                "split": sample.split,
                "annotation_progress": sample.annotation_progress,
                "review_status": sample.review_status,
                "notes": sample.notes,
                "metadata": _parse_json_dict(sample.metadata_json),
                "tags": sorted(tag.name for tag in sample.tags),
                "annotations": [
                    {
                        "id": annotation.id,
                        "class_id": annotation.class_id,
                        "label": annotation.label,
                        "shape_type": annotation.shape_type,
                        "points": annotation.points,
                        "flags": annotation.flags,
                        "attributes": annotation.attributes,
                        "group_id": annotation.group_id,
                        "z_order": annotation.z_order,
                        "locked": annotation.locked,
                        "hidden": annotation.hidden,
                        "source": annotation.source,
                        "notes": annotation.notes,
                    }
                    for annotation in sample_annotations
                ],
            }
        )

    return DatasetSnapshotContent(
        schema_version=1,
        dataset={
            "id": dataset.id,
            "revision": dataset.revision,
            "name": dataset.name,
            "description": dataset.description,
            "task_type": dataset.task_type,
            "root_path": dataset.root_path,
            "source": dataset.source,
            "modality": dataset.modality,
            "license": dataset.license,
            "owner": dataset.owner,
            "project": dataset.project,
            "notes": dataset.notes,
            "created_at": dataset.created_at.isoformat(),
            "updated_at": dataset.updated_at.isoformat(),
        },
        sample_query=query,
        export_config=export_config,
        class_map=class_map,
        tag_catalog=[
            {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "description": tag.description,
                "parent_id": tag.parent_id,
                "aliases": _parse_json_list(tag.aliases_json),
            }
            for tag in tags
        ],
        annotation_class_catalog=[
            {
                "id": item.id,
                "name": item.name,
                "color": item.color,
                "description": item.description,
            }
            for item in annotation_classes
        ],
        sample_count=len(snapshot_samples),
        annotation_count=annotation_count,
        samples=snapshot_samples,
    )


def create_snapshot(
    session: Session,
    dataset_id: int,
    payload: DatasetSnapshotCreate,
) -> DatasetSnapshotRead:
    dataset = get_dataset_or_404(session, dataset_id)
    expected_revision = dataset.revision
    content = _build_snapshot_content(session, dataset, payload)
    content_dict = content.model_dump(mode="json")
    content_sha256 = hashlib.sha256(_canonical_json(content_dict).encode("utf-8")).hexdigest()
    created_at = utc_now().astimezone(timezone.utc)
    relative_artifact = f"dataset-{dataset_id}/snapshot-{uuid4().hex}.json"
    artifact_path = _artifact_path(relative_artifact)

    # End the read transaction, then publish through an atomic conditional insert.
    # The INSERT sees the latest committed revision and cannot race another writer.
    session.commit()
    statement = text(
        "INSERT INTO dataset_snapshots "
        "(dataset_id, dataset_revision, name, artifact_path, content_sha256, "
        "sample_count, annotation_count, class_count, query_json, export_config_json, created_at) "
        "SELECT id, revision, :name, :artifact_path, :content_sha256, :sample_count, "
        ":annotation_count, :class_count, :query_json, :export_config_json, :created_at "
        "FROM datasets WHERE id = :dataset_id AND revision = :expected_revision "
        "RETURNING id"
    )
    try:
        snapshot_id = session.connection().execute(
            statement,
            {
                "dataset_id": dataset_id,
                "expected_revision": expected_revision,
                "name": payload.name,
                "artifact_path": relative_artifact,
                "content_sha256": content_sha256,
                "sample_count": content.sample_count,
                "annotation_count": content.annotation_count,
                "class_count": len(content.class_map),
                "query_json": _canonical_json(payload.sample_query.model_dump(mode="json")),
                "export_config_json": _canonical_json(content.export_config.model_dump(mode="json")),
                "created_at": created_at,
            },
        ).scalar_one_or_none()
    except OperationalError as exc:
        session.rollback()
        raise DatasetSnapshotSchemaUnavailableError(
            "Dataset snapshot storage is unavailable. Run database migrations first."
        ) from exc
    if snapshot_id is None:
        session.rollback()
        raise DatasetSnapshotStaleError(
            "Dataset metadata changed while the snapshot was being built. Create it again."
        )

    document = DatasetSnapshotDocument(
        snapshot_id=int(snapshot_id),
        dataset_id=dataset_id,
        dataset_revision=expected_revision,
        created_at=created_at,
        content_sha256=content_sha256,
        content=content,
    )
    temp_path = artifact_path.with_suffix(".tmp")
    try:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(document.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, artifact_path)
        session.commit()
    except Exception:
        session.rollback()
        temp_path.unlink(missing_ok=True)
        artifact_path.unlink(missing_ok=True)
        raise

    snapshot = session.get(DatasetSnapshot, int(snapshot_id))
    if snapshot is None:
        artifact_path.unlink(missing_ok=True)
        raise DatasetSnapshotError("Snapshot record was not persisted.")
    return _read_model(snapshot)


def list_snapshots(session: Session, dataset_id: int) -> list[DatasetSnapshotRead]:
    get_dataset_or_404(session, dataset_id)
    try:
        snapshots = session.exec(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.dataset_id == dataset_id)
            .order_by(DatasetSnapshot.created_at.desc(), DatasetSnapshot.id.desc())
        ).all()
    except OperationalError as exc:
        raise DatasetSnapshotSchemaUnavailableError(
            "Dataset snapshot storage is unavailable. Run database migrations first."
        ) from exc
    return [_read_model(snapshot) for snapshot in snapshots]


def get_snapshot(session: Session, dataset_id: int, snapshot_id: int) -> DatasetSnapshot:
    get_dataset_or_404(session, dataset_id)
    try:
        snapshot = session.get(DatasetSnapshot, snapshot_id)
    except OperationalError as exc:
        raise DatasetSnapshotSchemaUnavailableError(
            "Dataset snapshot storage is unavailable. Run database migrations first."
        ) from exc
    if snapshot is None or snapshot.dataset_id != dataset_id:
        raise DatasetSnapshotError(f"Snapshot {snapshot_id} was not found in dataset {dataset_id}.")
    return snapshot


def get_snapshot_read(session: Session, dataset_id: int, snapshot_id: int) -> DatasetSnapshotRead:
    return _read_model(get_snapshot(session, dataset_id, snapshot_id))


def snapshot_artifact_path(session: Session, dataset_id: int, snapshot_id: int) -> Path:
    snapshot = get_snapshot(session, dataset_id, snapshot_id)
    path = _artifact_path(snapshot.artifact_path)
    if not path.is_file():
        raise DatasetSnapshotArtifactError("Snapshot artifact is no longer available.")
    return path


def read_snapshot_document(
    session: Session,
    dataset_id: int,
    snapshot_id: int,
) -> DatasetSnapshotDocument:
    snapshot = get_snapshot(session, dataset_id, snapshot_id)
    path = snapshot_artifact_path(session, dataset_id, snapshot_id)
    try:
        document = DatasetSnapshotDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DatasetSnapshotArtifactError("Snapshot artifact cannot be read or is invalid.") from exc
    canonical_content = _canonical_json(document.content.model_dump(mode="json"))
    actual_hash = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
    if actual_hash != snapshot.content_sha256 or document.content_sha256 != snapshot.content_sha256:
        raise DatasetSnapshotArtifactError("Snapshot artifact integrity check failed.")
    return document


def delete_dataset_snapshot_records(session: Session, dataset_id: int) -> list[Path]:
    try:
        snapshots = session.exec(
            select(DatasetSnapshot).where(DatasetSnapshot.dataset_id == dataset_id)
        ).all()
    except OperationalError:
        return []
    paths = [_artifact_path(snapshot.artifact_path) for snapshot in snapshots]
    for snapshot in snapshots:
        session.delete(snapshot)
    return paths


def remove_snapshot_artifacts(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
