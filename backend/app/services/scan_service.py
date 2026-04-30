from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.sample import Sample
from app.schemas.scan import ScanRequest, ScanResult
from app.services.dataset_service import get_dataset_or_404
from app.utils.file_types import detect_file_type, detect_mime_type
from app.utils.hashing import sha256_file
from app.utils.paths import relative_to_root, resolve_local_path


def _file_modified_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _is_under_root(path_value: str, root: Path) -> bool:
    try:
        Path(path_value).resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _apply_file_metadata(sample: Sample, path: Path, root: Path, file_type: str, file_hash: str) -> None:
    stat = path.stat()
    sample.filename = path.name
    sample.absolute_path = str(path.resolve())
    sample.relative_path = relative_to_root(path, root)
    sample.file_size = stat.st_size
    sample.extension = path.suffix.lower()
    sample.file_type = file_type
    sample.mime_type = detect_mime_type(path)
    sample.file_hash = file_hash
    sample.file_status = "normal"
    sample.file_modified_at = _file_modified_at(path)
    sample.last_scanned_at = utc_now()
    sample.updated_at = utc_now()


def _reject_unsafe_scan_root(root: Path) -> None:
    resolved = root.resolve()
    if resolved.parent == resolved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refusing to scan a filesystem root. Please choose a specific dataset folder.",
        )

    if resolved.anchor and str(resolved) == resolved.anchor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refusing to scan a drive root. Please choose a specific dataset folder.",
        )


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
    _reject_unsafe_scan_root(root)

    scanned = 0
    imported = 0
    updated = 0
    unchanged = 0
    missing = 0
    skipped_unsupported = 0
    errors: list[str] = []
    seen_sample_ids: set[int] = set()

    existing_samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
    existing_by_path = {sample.absolute_path: sample for sample in existing_samples}
    existing_under_root = [sample for sample in existing_samples if _is_under_root(sample.absolute_path, root)]

    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue

            scanned += 1
            file_type = detect_file_type(path)
            if not file_type:
                skipped_unsupported += 1
                continue

            absolute_path = str(path.resolve())
            file_hash = sha256_file(path)
            existing = existing_by_path.get(absolute_path)
            if existing:
                seen_sample_ids.add(existing.id or 0)
                changed = existing.file_hash != file_hash or existing.file_size != path.stat().st_size
                _apply_file_metadata(existing, path, root, file_type, file_hash)
                session.add(existing)
                if changed:
                    updated += 1
                else:
                    unchanged += 1
                continue

            sample = Sample(
                dataset_id=dataset_id,
                filename=path.name,
                absolute_path=absolute_path,
                relative_path=relative_to_root(path, root),
                file_size=path.stat().st_size,
                extension=path.suffix.lower(),
                file_type=file_type,
                mime_type=detect_mime_type(path),
                file_hash=file_hash,
                file_status="normal",
                file_modified_at=_file_modified_at(path),
                last_scanned_at=utc_now(),
            )
            session.add(sample)
            imported += 1
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    for sample in existing_under_root:
        if sample.id in seen_sample_ids:
            continue
        try:
            if not Path(sample.absolute_path).exists():
                sample.file_status = "missing"
                sample.last_scanned_at = utc_now()
                sample.updated_at = utc_now()
                session.add(sample)
                missing += 1
        except OSError as exc:
            sample.file_status = "permission_denied"
            sample.last_scanned_at = utc_now()
            sample.updated_at = utc_now()
            session.add(sample)
            errors.append(f"{sample.absolute_path}: {exc}")

    session.commit()

    return ScanResult(
        dataset_id=dataset_id,
        root_path=str(root),
        scanned=scanned,
        imported=imported,
        updated=updated,
        unchanged=unchanged,
        missing=missing,
        skipped_existing=unchanged,
        skipped_unsupported=skipped_unsupported,
        errors=errors[:50],
    )
