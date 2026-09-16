from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import time

from sqlmodel import Session, select

from app.models.sample import Sample
from app.services.thumbnail_service import (
    THUMBNAIL_SPEC_VERSION,
    thumbnail_cache_digest,
    thumbnail_cache_root,
)


MAX_ERRORS = 50
STALE_PART_SECONDS = 60 * 60


@dataclass(frozen=True)
class CacheEntry:
    path: Path
    digest: str
    size: int
    modified_at: float


def _managed_webp_parts(relative: Path) -> tuple[str, str] | None:
    parts = relative.parts
    if len(parts) != 3 or relative.suffix.lower() != ".webp":
        return None
    digest = relative.stem.lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return None
    if parts[1].lower() != digest[:2]:
        return None
    return parts[0], digest


def maintain_thumbnail_cache(
    session: Session,
    *,
    max_bytes: int,
    now_timestamp: float | None = None,
    checkpoint: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda _current, _total: None,
    prune_started: Callable[[int, int], None] = lambda _current, _total: None,
) -> dict[str, object]:
    if max_bytes <= 0:
        raise ValueError("Thumbnail cache capacity must be positive.")
    root = thumbnail_cache_root()
    now = now_timestamp if now_timestamp is not None else time.time()
    if not root.exists():
        return _empty_result(max_bytes)

    paths = list(root.rglob("*"))
    total_paths = len(paths)
    current_entries: dict[str, CacheEntry] = {}
    old_entries: list[CacheEntry] = []
    stale_parts: list[Path] = []
    ignored_count = 0
    errors: list[dict[str, object]] = []
    error_total = [0]
    size_before = 0

    for index, path in enumerate(paths, start=1):
        if index == 1 or index % 250 == 0:
            checkpoint()
            progress(index - 1, total_paths)
        try:
            if path.is_symlink():
                ignored_count += 1
                continue
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            stat = path.stat()
        except OSError as exc:
            _append_error(errors, path, exc, error_total)
            continue
        if path.suffix.lower() == ".part":
            if now - stat.st_mtime >= STALE_PART_SECONDS:
                stale_parts.append(path)
            continue
        managed = _managed_webp_parts(relative)
        if managed is None:
            ignored_count += 1
            continue
        version, digest = managed
        entry = CacheEntry(path, digest, stat.st_size, stat.st_mtime)
        size_before += stat.st_size
        if version == THUMBNAIL_SPEC_VERSION:
            current_entries[digest] = entry
        else:
            old_entries.append(entry)
    progress(total_paths, total_paths)
    checkpoint()
    prune_started(total_paths, total_paths)
    all_managed_entries = [*current_entries.values(), *old_entries]

    removed = {
        "old_spec": [0, 0],
        "orphan": [0, 0],
        "capacity": [0, 0],
        "stale_part": [0, 0],
    }
    for path in stale_parts:
        _remove_path(path, 0, "stale_part", removed, errors, error_total)
    for entry in old_entries:
        _remove_path(entry.path, entry.size, "old_spec", removed, errors, error_total)

    orphan_candidates = set(current_entries)
    for index, file_hash in enumerate(session.exec(select(Sample.file_hash).distinct())):
        orphan_candidates.discard(thumbnail_cache_digest(str(file_hash)))
        if index and index % 1000 == 0:
            checkpoint()
    for digest in sorted(orphan_candidates):
        entry = current_entries.pop(digest)
        _remove_path(entry.path, entry.size, "orphan", removed, errors, error_total)

    remaining_entries = sorted(
        (entry for entry in current_entries.values() if entry.path.exists()),
        key=lambda entry: (entry.modified_at, str(entry.path)),
    )
    remaining_size = sum(entry.size for entry in remaining_entries)
    for entry in remaining_entries:
        if remaining_size <= max_bytes:
            break
        if _remove_path(
            entry.path,
            entry.size,
            "capacity",
            removed,
            errors,
            error_total,
        ):
            remaining_size -= entry.size
        checkpoint()

    actual_size_after = sum(
        entry.size
        for entry in all_managed_entries
        if entry.path.exists() and entry.path.is_file()
    )

    return {
        "files_scanned": total_paths,
        "size_before_bytes": size_before,
        "size_after_bytes": actual_size_after,
        "capacity_bytes": max_bytes,
        "old_spec_removed_count": removed["old_spec"][0],
        "old_spec_removed_bytes": removed["old_spec"][1],
        "orphan_removed_count": removed["orphan"][0],
        "orphan_removed_bytes": removed["orphan"][1],
        "capacity_removed_count": removed["capacity"][0],
        "capacity_removed_bytes": removed["capacity"][1],
        "stale_part_removed_count": removed["stale_part"][0],
        "ignored_count": ignored_count,
        "error_count": error_total[0],
        "errors": errors,
        "spec_version": THUMBNAIL_SPEC_VERSION,
    }


def _empty_result(max_bytes: int) -> dict[str, object]:
    return {
        "files_scanned": 0,
        "size_before_bytes": 0,
        "size_after_bytes": 0,
        "capacity_bytes": max_bytes,
        "old_spec_removed_count": 0,
        "old_spec_removed_bytes": 0,
        "orphan_removed_count": 0,
        "orphan_removed_bytes": 0,
        "capacity_removed_count": 0,
        "capacity_removed_bytes": 0,
        "stale_part_removed_count": 0,
        "ignored_count": 0,
        "error_count": 0,
        "errors": [],
        "spec_version": THUMBNAIL_SPEC_VERSION,
    }


def _remove_path(
    path: Path,
    size: int,
    category: str,
    removed: dict[str, list[int]],
    errors: list[dict[str, object]],
    error_total: list[int],
) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        _append_error(errors, path, exc, error_total)
        return False
    removed[category][0] += 1
    removed[category][1] += size
    return True


def _append_error(
    errors: list[dict[str, object]],
    path: Path,
    exc: OSError,
    error_total: list[int],
) -> None:
    error_total[0] += 1
    if len(errors) < MAX_ERRORS:
        errors.append(
            {
                "filename": path.name,
                "message": str(exc)[:500],
                "type": type(exc).__name__,
            }
        )
