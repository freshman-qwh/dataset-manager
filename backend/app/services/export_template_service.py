from sqlmodel import Session

from app.schemas.export_template import ExportTemplateResponse
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import get_filtered_samples


def export_template(session: Session, dataset_id: int, template_format: str) -> ExportTemplateResponse:
    dataset = get_dataset_or_404(session, dataset_id)
    samples = get_filtered_samples(session, dataset_id, sort_by="relative_path", sort_order="asc")
    normalized = template_format.lower()
    if normalized == "csv":
        payload = _csv_payload(samples)
        description = "Sample-level label table. This is the most useful current export because the MVP stores tags and splits, not bounding boxes."
    elif normalized == "coco":
        payload = _coco_payload(dataset.name, samples)
        description = "COCO skeleton with images and categories. Object annotations are empty until annotation geometry is implemented."
    elif normalized == "yolo":
        payload = _yolo_payload(samples)
        description = "YOLO planning skeleton with class names and suggested paths. Label txt files require annotation geometry in a later version."
    else:
        payload = {
            "supported_formats": ["csv", "coco", "yolo"],
            "message": f"Unsupported export template format: {template_format}",
        }
        description = "Unsupported export template request."

    return ExportTemplateResponse(
        dataset_id=dataset_id,
        format=normalized,
        description=description,
        payload=payload,
    )


def _csv_payload(samples) -> dict[str, object]:
    return {
        "columns": ["relative_path", "split", "tags", "notes", "file_type", "file_hash", "metadata"],
        "rows": [
            {
                "relative_path": sample.relative_path,
                "split": sample.split,
                "tags": [tag.name for tag in sample.tags],
                "notes": sample.notes,
                "file_type": sample.file_type,
                "file_hash": sample.file_hash,
                "metadata": sample.metadata_json,
            }
            for sample in samples
        ],
    }


def _coco_payload(dataset_name: str, samples) -> dict[str, object]:
    image_samples = [sample for sample in samples if sample.file_type == "image"]
    categories = sorted({tag.name for sample in image_samples for tag in sample.tags})
    return {
        "info": {"description": dataset_name},
        "licenses": [],
        "images": [
            {
                "id": sample.id,
                "file_name": sample.relative_path,
            }
            for sample in image_samples
        ],
        "annotations": [],
        "categories": [{"id": index + 1, "name": name} for index, name in enumerate(categories)],
    }


def _yolo_payload(samples) -> dict[str, object]:
    image_samples = [sample for sample in samples if sample.file_type == "image"]
    classes = sorted({tag.name for sample in image_samples for tag in sample.tags})
    return {
        "classes": classes,
        "samples": [
            {
                "image": sample.relative_path,
                "label": f"labels/{sample.relative_path}.txt",
                "split": sample.split or "unassigned",
                "tags": [tag.name for tag in sample.tags],
            }
            for sample in image_samples
        ],
    }
