from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.sample import Sample
from app.schemas.scan import ScanRequest, ScanResult
from app.services.dataset_service import get_dataset_or_404
from app.services.dataset_revision_service import DatasetRevisionTracker
from app.services.benchmark_import_service import BenchmarkInventory, inspect_benchmark
from app.utils.file_types import detect_file_type, detect_mime_type
from app.utils.hashing import sha256_file
from app.utils.paths import relative_to_root, resolve_local_path


ScanCheckpoint = Callable[[], None]
ScanProgress = Callable[[str, int, int | None, int], None]


@dataclass(frozen=True)
class FileCandidate:
    path: Path
    absolute_path: str
    relative_path: str
    file_type: str
    size: int
    modified_at: datetime


@dataclass
class ScanCounters:
    scanned: int = 0
    imported: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    skipped_unsupported: int = 0
    hashed: int = 0
    hash_skipped_unchanged: int = 0
    batches_committed: int = 0
    error_count: int = 0


class ScanStopped(RuntimeError):
    """Carries the safely committed partial result when a checkpoint stops a scan."""

    def __init__(self, result: ScanResult):
        super().__init__("The scan stopped at a cooperative checkpoint.")
        self.result = result


def _record_error(counters: ScanCounters, errors: list[str], message: str) -> None:
    counters.error_count += 1
    if len(errors) < 50:
        errors.append(message[:1000])


def _is_under_root(path_value: str, root: Path) -> bool:
    try:
        Path(path_value).resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _reject_unsafe_scan_root(root: Path) -> None:
    resolved = root.resolve()
    if resolved.parent == resolved or (resolved.anchor and str(resolved) == resolved.anchor):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refusing to scan a filesystem root. Please choose a specific dataset folder.",
        )


def resolve_scan_root(session: Session, dataset_id: int, payload: ScanRequest) -> Path:
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
    return root


def _mtime_matches(stored: datetime | None, current: datetime) -> bool:
    if stored is None:
        return False
    normalized = stored.replace(tzinfo=timezone.utc) if stored.tzinfo is None else stored
    return abs(normalized.timestamp() - current.timestamp()) < 0.00001


def _apply_file_metadata(
    sample: Sample,
    candidate: FileCandidate,
    file_hash: str,
    scanned_at: datetime,
) -> None:
    sample.filename = candidate.path.name
    sample.absolute_path = candidate.absolute_path
    sample.relative_path = candidate.relative_path
    sample.file_size = candidate.size
    sample.extension = candidate.path.suffix.lower()
    sample.file_type = candidate.file_type
    sample.mime_type = detect_mime_type(candidate.path)
    sample.file_hash = file_hash
    sample.file_status = "normal"
    sample.file_modified_at = candidate.modified_at
    sample.last_scanned_at = scanned_at
    sample.updated_at = scanned_at


def _file_metadata_changed(
    sample: Sample,
    candidate: FileCandidate,
    file_hash: str,
) -> bool:
    return any(
        (
            sample.filename != candidate.path.name,
            sample.absolute_path != candidate.absolute_path,
            sample.relative_path != candidate.relative_path,
            sample.file_size != candidate.size,
            sample.extension != candidate.path.suffix.lower(),
            sample.file_type != candidate.file_type,
            sample.mime_type != detect_mime_type(candidate.path),
            sample.file_hash != file_hash,
            sample.file_status != "normal",
            not _mtime_matches(sample.file_modified_at, candidate.modified_at),
        )
    )


def _iter_candidates(
    root: Path,
    counters: ScanCounters,
    errors: list[str],
    checkpoint: ScanCheckpoint,
    inventory: BenchmarkInventory | None = None,
) -> Iterator[FileCandidate]:
    def record_walk_error(exc: OSError) -> None:
        _record_error(counters, errors, str(exc))

    for directory, _, filenames in os.walk(root, onerror=record_walk_error):
        checkpoint()
        for filename in filenames:
            checkpoint()
            path = Path(directory) / filename
            counters.scanned += 1
            if inventory is not None and inventory.format != "folder" and str(path.resolve()) not in inventory.images:
                counters.skipped_unsupported += 1
                continue
            file_type = detect_file_type(path)
            if not file_type:
                counters.skipped_unsupported += 1
                continue
            try:
                stat = path.stat()
                resolved = path.resolve()
                yield FileCandidate(
                    path=path,
                    absolute_path=str(resolved),
                    relative_path=relative_to_root(path, root),
                    file_type=file_type,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                )
            except OSError as exc:
                _record_error(counters, errors, f"{path}: {exc}")


def _hash_candidates(
    candidates: list[FileCandidate],
    *,
    hash_workers: int,
    counters: ScanCounters,
    errors: list[str],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not candidates:
        return hashes
    with ThreadPoolExecutor(
        max_workers=min(max(hash_workers, 1), len(candidates)),
        thread_name_prefix="dataset-scan-hash",
    ) as executor:
        futures = {executor.submit(sha256_file, item.path): item for item in candidates}
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                hashes[candidate.absolute_path] = future.result()
            except OSError as exc:
                _record_error(counters, errors, f"{candidate.path}: {exc}")
    return hashes


def _fill_existing_benchmark_metadata(
    sample: Sample,
    candidate: FileCandidate,
    inventory: BenchmarkInventory | None,
    category_ids: dict[str, int] | None,
) -> bool:
    """Explicit recognition fills missing semantics, never manual decisions."""
    benchmark = inventory.images.get(candidate.absolute_path) if inventory else None
    if benchmark is None:
        return False
    fields = {
        "category_id": (category_ids or {}).get(benchmark.category),
        "import_format": inventory.format,
        "official_split": benchmark.split,
        "benchmark_label": benchmark.label,
        "benchmark_defect_type": benchmark.defect,
        "mask_path": benchmark.mask_path,
    }
    changed = False
    for name, value in fields.items():
        if getattr(sample, name) in (None, "") and value not in (None, ""):
            setattr(sample, name, value)
            changed = True
    return changed


def _process_batch(
    session: Session,
    dataset_id: int,
    candidates: list[FileCandidate],
    *,
    counters: ScanCounters,
    errors: list[str],
    seen_sample_ids: set[int],
    hash_workers: int,
    scanned_at: datetime,
    revision_tracker: DatasetRevisionTracker,
    inventory: BenchmarkInventory | None = None,
    category_ids: dict[str, int] | None = None,
    assigned_batch_id: int | None = None,
    assigned_batch_code: str | None = None,
    triage_policy_version: int = 1,
    recognize_existing: bool = False,
) -> None:
    absolute_paths = [candidate.absolute_path for candidate in candidates]
    existing_samples = list(
        session.exec(
            select(Sample).where(
                Sample.dataset_id == dataset_id,
                Sample.absolute_path.in_(absolute_paths),
            )
        ).all()
    )
    existing_by_path = {sample.absolute_path: sample for sample in existing_samples}
    needs_hash: list[FileCandidate] = []
    batch_changed = False

    for candidate in candidates:
        existing = existing_by_path.get(candidate.absolute_path)
        if (
            existing is not None
            and existing.file_size == candidate.size
            and _mtime_matches(existing.file_modified_at, candidate.modified_at)
        ):
            if existing.id is not None:
                seen_sample_ids.add(existing.id)
            metadata_changed = _file_metadata_changed(existing, candidate, existing.file_hash)
            _apply_file_metadata(existing, candidate, existing.file_hash, scanned_at)
            if recognize_existing:
                metadata_changed = _fill_existing_benchmark_metadata(existing, candidate, inventory, category_ids) or metadata_changed
            session.add(existing)
            if metadata_changed:
                counters.updated += 1
                batch_changed = True
            else:
                counters.unchanged += 1
            counters.hash_skipped_unchanged += 1
        else:
            needs_hash.append(candidate)

    hashes = _hash_candidates(
        needs_hash,
        hash_workers=hash_workers,
        counters=counters,
        errors=errors,
    )
    counters.hashed += len(hashes)
    for candidate in needs_hash:
        file_hash = hashes.get(candidate.absolute_path)
        if file_hash is None:
            continue
        existing = existing_by_path.get(candidate.absolute_path)
        if existing is not None:
            if existing.id is not None:
                seen_sample_ids.add(existing.id)
            metadata_changed = _file_metadata_changed(existing, candidate, file_hash)
            _apply_file_metadata(existing, candidate, file_hash, scanned_at)
            if recognize_existing:
                metadata_changed = _fill_existing_benchmark_metadata(existing, candidate, inventory, category_ids) or metadata_changed
            session.add(existing)
            if metadata_changed:
                counters.updated += 1
                batch_changed = True
            else:
                counters.unchanged += 1
            continue

        sample = Sample(
            dataset_id=dataset_id,
            filename=candidate.path.name,
            absolute_path=candidate.absolute_path,
            relative_path=candidate.relative_path,
            file_size=candidate.size,
            extension=candidate.path.suffix.lower(),
            file_type=candidate.file_type,
            mime_type=detect_mime_type(candidate.path),
            file_hash=file_hash,
            file_status="normal",
            file_modified_at=candidate.modified_at,
            last_scanned_at=scanned_at,
        )
        if assigned_batch_id is not None:
            sample.batch_id = assigned_batch_id
            sample.capture_batch_id = assigned_batch_code
        benchmark = inventory.images.get(candidate.absolute_path) if inventory else None
        if benchmark is not None:
            sample.category_id = (category_ids or {}).get(benchmark.category)
            sample.import_format = inventory.format
            sample.official_split = benchmark.split
            sample.split = benchmark.split
            sample.benchmark_label = benchmark.label
            sample.benchmark_defect_type = benchmark.defect
            sample.mask_path = benchmark.mask_path
            sample.triage_status = "ok" if benchmark.label == "normal" else "ng"
            sample.ok_grade = "clear" if benchmark.label == "normal" else None
            sample.triaged_at = scanned_at
            sample.triage_version = 1
            sample.triage_policy_version = triage_policy_version
            sample.triaged_file_hash = file_hash
        session.add(sample)
        counters.imported += 1
        batch_changed = True

    if batch_changed:
        revision_tracker.bump_once(session)
    session.commit()
    counters.batches_committed += 1


def _mark_missing_samples(
    session: Session,
    dataset_id: int,
    root: Path,
    *,
    seen_sample_ids: set[int],
    counters: ScanCounters,
    errors: list[str],
    checkpoint: ScanCheckpoint,
    batch_size: int,
    revision_tracker: DatasetRevisionTracker,
) -> None:
    last_id = 0
    while True:
        checkpoint()
        samples = list(
            session.exec(
                select(Sample)
                .where(Sample.dataset_id == dataset_id, Sample.id > last_id)
                .order_by(Sample.id)
                .limit(batch_size)
            ).all()
        )
        if not samples:
            break
        last_id = samples[-1].id or last_id
        changed = False
        for sample in samples:
            if sample.id in seen_sample_ids or not _is_under_root(sample.absolute_path, root):
                continue
            try:
                Path(sample.absolute_path).stat()
            except FileNotFoundError:
                now = utc_now()
                sample.file_status = "missing"
                sample.last_scanned_at = now
                sample.updated_at = now
                session.add(sample)
                counters.missing += 1
                changed = True
            except OSError as exc:
                now = utc_now()
                sample.file_status = "permission_denied"
                sample.last_scanned_at = now
                sample.updated_at = now
                session.add(sample)
                changed = True
                _record_error(counters, errors, f"{sample.absolute_path}: {exc}")
        if changed:
            revision_tracker.bump_once(session)
            session.commit()


def _build_result(
    dataset_id: int,
    root: Path,
    counters: ScanCounters,
    errors: list[str],
    inventory: BenchmarkInventory | None = None,
    assigned_batch_id: int | None = None,
) -> ScanResult:
    return ScanResult(
        dataset_id=dataset_id,
        root_path=str(root),
        scanned=counters.scanned,
        imported=counters.imported,
        updated=counters.updated,
        unchanged=counters.unchanged,
        missing=counters.missing,
        skipped_existing=counters.unchanged,
        skipped_unsupported=counters.skipped_unsupported,
        hashed=counters.hashed,
        hash_skipped_unchanged=counters.hash_skipped_unchanged,
        batches_committed=counters.batches_committed,
        error_count=counters.error_count,
        errors=errors,
        detected_format=inventory.format if inventory else "folder",
        assigned_batch_id=assigned_batch_id,
        benchmark_images=len(inventory.images) if inventory else 0,
        linked_masks=sum(row.mask_path is not None for row in inventory.images.values()) if inventory else 0,
        import_warnings=inventory.warnings[:50] if inventory else [],
    )


def prepare_scan_batch(session: Session, dataset_id: int, payload: ScanRequest):
    """Resolve a batch once; jobs persist the numeric choice for retry stability."""
    from app.models.organization import DatasetBatch
    if payload.batch_id is not None:
        batch = session.get(DatasetBatch, payload.batch_id)
        if batch is None or batch.dataset_id != dataset_id:
            raise HTTPException(422, "所选批次不属于当前数据集。")
        return batch
    if payload.new_batch_name is not None:
        existing = session.exec(select(DatasetBatch).where(DatasetBatch.dataset_id == dataset_id, DatasetBatch.name == payload.new_batch_name)).first()
        if existing:
            raise HTTPException(409, "同名批次已存在，请选择已有批次。")
        batch = DatasetBatch(dataset_id=dataset_id, name=payload.new_batch_name, code="batch-" + uuid4().hex)
        session.add(batch)
        session.flush()
        return batch
    return None


def preview_import(session: Session, dataset_id: int, payload: ScanRequest):
    from app.schemas.scan import ImportPreview
    root = resolve_scan_root(session, dataset_id, payload)
    if payload.batch_id is not None:
        prepare_scan_batch(session, dataset_id, payload)
    inventory = inspect_benchmark(root, payload.import_format)
    if inventory.format != "folder":
        result = inventory.preview()
        result.warnings.append("已登记图片仅补充空的类别、官方划分与 mask 等识别信息，已有人工判定、批次、工件及实际划分保持原值。" if payload.recognize_existing else "仅新登记图片写入类别、官方划分和真值；已有记录的人工判定、批次及划分保持原值。")
        return result
    counters = ScanCounters()
    errors: list[str] = []
    count = sum(candidate.file_type == "image" for candidate in _iter_candidates(root, counters, errors, lambda: None))
    return ImportPreview(detected_format="folder", image_count=count, warnings=errors)


def scan_dataset(
    session: Session,
    dataset_id: int,
    payload: ScanRequest,
    *,
    batch_size: int = 100,
    hash_workers: int = 4,
    checkpoint: ScanCheckpoint | None = None,
    progress: ScanProgress | None = None,
) -> ScanResult:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")
    if hash_workers < 1:
        raise ValueError("hash_workers must be at least 1.")

    root = resolve_scan_root(session, dataset_id, payload)
    dataset = get_dataset_or_404(session, dataset_id)
    counters = ScanCounters()
    errors: list[str] = []
    seen_sample_ids: set[int] = set()
    pending: list[FileCandidate] = []
    check = checkpoint or (lambda: None)
    report = progress or (lambda stage, current, total, error_count: None)
    scanned_at = utc_now()
    revision_tracker = DatasetRevisionTracker(dataset_id)

    def guarded_checkpoint() -> None:
        try:
            check()
        except Exception as exc:
            raise ScanStopped(_build_result(dataset_id, root, counters, errors, inventory, assigned_batch_id)) from exc

    def guarded_report(
        stage: str,
        current: int,
        total: int | None,
        error_count: int,
    ) -> None:
        try:
            report(stage, current, total, error_count)
        except Exception as exc:
            raise ScanStopped(_build_result(dataset_id, root, counters, errors, inventory, assigned_batch_id)) from exc

    inventory = BenchmarkInventory("folder")
    assigned_batch_id = None
    inventory = inspect_benchmark(root, payload.import_format, guarded_checkpoint)
    batch = prepare_scan_batch(session, dataset_id, payload)
    assigned_batch_id = batch.id if batch else None
    assigned_batch_code = batch.code if batch else None
    category_ids: dict[str, int] = {}
    if inventory.images:
        from app.models.organization import DatasetCategory
        for name in sorted({row.category for row in inventory.images.values()}):
            category = session.exec(select(DatasetCategory).where(DatasetCategory.dataset_id == dataset_id, DatasetCategory.name == name)).first()
            if category is None:
                category = DatasetCategory(dataset_id=dataset_id, name=name)
                session.add(category)
                session.flush()
            category_ids[name] = category.id
    if batch is not None or category_ids:
        session.commit()

    guarded_report("enumerating", 0, None, 0)
    for candidate in _iter_candidates(root, counters, errors, guarded_checkpoint, inventory):
        pending.append(candidate)
        if len(pending) < batch_size:
            continue
        guarded_checkpoint()
        guarded_report("hashing", counters.scanned, None, counters.error_count)
        _process_batch(
            session,
            dataset_id,
            pending,
            counters=counters,
            errors=errors,
            seen_sample_ids=seen_sample_ids,
            hash_workers=hash_workers,
            scanned_at=scanned_at,
            revision_tracker=revision_tracker,
            inventory=inventory, category_ids=category_ids,
            assigned_batch_id=assigned_batch_id, assigned_batch_code=assigned_batch_code,
            triage_policy_version=dataset.triage_policy_version,
            recognize_existing=payload.recognize_existing,
        )
        guarded_report("writing", counters.scanned, None, counters.error_count)
        pending = []

    if pending:
        guarded_checkpoint()
        guarded_report("hashing", counters.scanned, None, counters.error_count)
        _process_batch(
            session,
            dataset_id,
            pending,
            counters=counters,
            errors=errors,
            seen_sample_ids=seen_sample_ids,
            hash_workers=hash_workers,
            scanned_at=scanned_at,
            revision_tracker=revision_tracker,
            inventory=inventory, category_ids=category_ids,
            assigned_batch_id=assigned_batch_id, assigned_batch_code=assigned_batch_code,
            triage_policy_version=dataset.triage_policy_version,
            recognize_existing=payload.recognize_existing,
        )
        guarded_report("writing", counters.scanned, None, counters.error_count)

    guarded_report(
        "missing_detection",
        counters.scanned,
        counters.scanned,
        counters.error_count,
    )
    _mark_missing_samples(
        session,
        dataset_id,
        root,
        seen_sample_ids=seen_sample_ids,
        counters=counters,
        errors=errors,
        checkpoint=guarded_checkpoint,
        batch_size=batch_size,
        revision_tracker=revision_tracker,
    )
    guarded_report("completed", counters.scanned, counters.scanned, counters.error_count)
    return _build_result(dataset_id, root, counters, errors, inventory, assigned_batch_id)
