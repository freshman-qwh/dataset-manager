import json
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from sqlmodel import Session

from app.services import annotation_service, dataset_service, sample_service


def export_labelme_zip(
    session: Session,
    dataset_id: int,
    *,
    search: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    sample_ids: list[int] | None = None,
    include_empty: bool = False,
) -> bytes:
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    samples = sample_service.get_filtered_samples(
        session,
        dataset_id,
        search=search,
        file_type="image",
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        sample_ids=sample_ids,
        sort_by="relative_path",
        sort_order="asc",
    )
    exported_files = 0
    skipped_empty_samples = 0
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for sample in samples:
            annotations = annotation_service.list_sample_annotations(session, sample.id or 0)
            if not annotations and not include_empty:
                skipped_empty_samples += 1
                continue
            payload = annotation_service.export_labelme_annotation(session, sample.id or 0)
            archive.writestr(_labelme_json_zip_path(sample.relative_path), _json_bytes(payload))
            exported_files += 1

        report = {
            "dataset_id": dataset_id,
            "dataset_name": dataset.name,
            "format": "labelme",
            "sample_count": len(samples),
            "exported_files": exported_files,
            "skipped_empty_samples": skipped_empty_samples,
            "include_empty": include_empty,
        }
        archive.writestr("export_report.json", _json_bytes(report))
    return buffer.getvalue()


def _labelme_json_zip_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    path = PurePosixPath(normalized)
    return str(PurePosixPath("annotations") / path.with_suffix(".json"))


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
