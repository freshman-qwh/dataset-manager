from pathlib import Path

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.scan import ScanRequest, ScanResult
from app.services.dataset_service import get_dataset_or_404
from app.utils.file_types import detect_file_type, detect_mime_type
from app.utils.hashing import sha256_file
from app.utils.paths import relative_to_root, resolve_local_path


def scan_dataset(session: Session, dataset_id: int, payload: ScanRequest) -> ScanResult:
    dataset = get_dataset_or_404(session, dataset_id)
    requested_root = payload.folder_path or dataset.root_path
    if not requested_root:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="folder_path is required when dataset.root_path is empty.",
        )

    root = resolve_local_path(requested_root)
    if not root.exists() or not root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Folder does not exist or is not a directory: {root}",
        )

    scanned = 0
    imported = 0
    skipped_existing = 0
    skipped_unsupported = 0
    errors: list[str] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        scanned += 1
        file_type = detect_file_type(path)
        if not file_type:
            skipped_unsupported += 1
            continue

        absolute_path = str(path.resolve())
        exists = session.exec(
            select(Sample).where(
                Sample.dataset_id == dataset_id,
                Sample.absolute_path == absolute_path,
            )
        ).first()
        if exists:
            skipped_existing += 1
            continue

        try:
            stat = path.stat()
            sample = Sample(
                dataset_id=dataset_id,
                filename=path.name,
                absolute_path=absolute_path,
                relative_path=relative_to_root(path, root),
                file_size=stat.st_size,
                extension=path.suffix.lower(),
                file_type=file_type,
                mime_type=detect_mime_type(path),
                file_hash=sha256_file(path),
            )
            session.add(sample)
            imported += 1
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    session.commit()

    return ScanResult(
        dataset_id=dataset_id,
        root_path=str(root),
        scanned=scanned,
        imported=imported,
        skipped_existing=skipped_existing,
        skipped_unsupported=skipped_unsupported,
        errors=errors[:50],
    )
