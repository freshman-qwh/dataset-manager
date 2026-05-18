from sqlmodel import Session

from app.services.dataset_service import get_dataset_or_404
from app.services import annotation_service
from app.services.sample_service import get_filtered_samples
from app.services.stats_service import get_dataset_stats


def export_manifest(
    session: Session,
    dataset_id: int,
    search: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    sample_ids: list[int] | None = None,
    sort_by: str = "relative_path",
    sort_order: str = "asc",
) -> dict:
    dataset = get_dataset_or_404(session, dataset_id)
    samples = get_filtered_samples(
        session,
        dataset_id,
        search=search,
        file_type=file_type,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        sample_ids=sample_ids,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    stats = get_dataset_stats(session, dataset_id)
    sample_ids = [sample.id for sample in samples if sample.id is not None]
    annotations = annotation_service.annotations_by_sample(session, sample_ids)

    return {
        "dataset": {
            "id": dataset.id,
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
        "filters": {
            "search": search,
            "file_type": file_type,
            "file_status": file_status,
            "tag": tag,
            "split": split,
            "review_status": review_status,
            "sample_ids": sample_ids or [],
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
        "stats": stats.model_dump(),
        "exported_sample_count": len(samples),
        "samples": [
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
                "file_modified_at": sample.file_modified_at.isoformat() if sample.file_modified_at else None,
                "last_scanned_at": sample.last_scanned_at.isoformat() if sample.last_scanned_at else None,
                "split": sample.split,
                "review_status": sample.review_status,
                "notes": sample.notes,
                "metadata_json": sample.metadata_json,
                "tags": [tag.name for tag in sample.tags],
                "annotations": [
                    {
                        "id": annotation.id,
                        "label": annotation.label,
                        "tag_id": annotation.tag_id,
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
                    for annotation in annotations.get(sample.id or 0, [])
                ],
            }
            for sample in samples
        ],
    }
