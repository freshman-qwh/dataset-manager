from sqlmodel import Session, select

from app.models.sample import Sample
from app.services.dataset_service import get_dataset_or_404
from app.services.stats_service import get_dataset_stats


def export_manifest(session: Session, dataset_id: int) -> dict:
    dataset = get_dataset_or_404(session, dataset_id)
    samples = session.exec(
        select(Sample).where(Sample.dataset_id == dataset_id).order_by(Sample.relative_path)
    ).all()
    stats = get_dataset_stats(session, dataset_id)

    return {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "task_type": dataset.task_type,
            "root_path": dataset.root_path,
            "created_at": dataset.created_at.isoformat(),
            "updated_at": dataset.updated_at.isoformat(),
        },
        "stats": stats.model_dump(),
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
                "split": sample.split,
                "notes": sample.notes,
                "tags": [tag.name for tag in sample.tags],
            }
            for sample in samples
        ],
    }
