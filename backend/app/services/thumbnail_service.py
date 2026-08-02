from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageOps

from app.core.config import get_settings


THUMBNAIL_SPEC_VERSION = "v1"
THUMBNAIL_MAX_SIZE = (640, 480)
THUMBNAIL_QUALITY = 82
THUMBNAIL_WORKERS = 2
MAX_ERRORS = 50


@dataclass(frozen=True)
class ThumbnailCandidate:
    sample_id: int
    path: Path
    file_hash: str
    file_size: int
    file_modified_at: datetime | None


class ThumbnailGenerationStopped(RuntimeError):
    def __init__(self, result: dict[str, object]):
        super().__init__("Thumbnail generation stopped.")
        self.result = result


def utc_from_timestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, timezone.utc)


def thumbnail_cache_root() -> Path:
    return get_settings().storage_root / "thumbnails"


def _cache_digest(file_hash: str) -> str:
    return sha256(f"{THUMBNAIL_SPEC_VERSION}:{file_hash}".encode("utf-8")).hexdigest()


def thumbnail_path(file_hash: str) -> Path:
    digest = _cache_digest(file_hash)
    return (
        thumbnail_cache_root()
        / THUMBNAIL_SPEC_VERSION
        / digest[:2]
        / f"{digest}.webp"
    )


def is_thumbnail_cached(file_hash: str) -> bool:
    path = thumbnail_path(file_hash)
    return path.exists() and path.is_file()


def _same_timestamp(actual: float, expected: datetime | None) -> bool:
    if expected is None:
        return True
    normalized = expected if expected.tzinfo is not None else expected.replace(tzinfo=timezone.utc)
    return abs(actual - normalized.timestamp()) < 0.001


def generate_thumbnail(candidate: ThumbnailCandidate) -> str:
    target = thumbnail_path(candidate.file_hash)
    if target.exists() and target.is_file():
        return "cached"

    stat = candidate.path.stat()
    if stat.st_size != candidate.file_size or not _same_timestamp(
        stat.st_mtime,
        candidate.file_modified_at,
    ):
        return "stale"

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.stem}-",
            suffix=".part",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with Image.open(candidate.path) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")
            image.thumbnail(THUMBNAIL_MAX_SIZE, Image.Resampling.LANCZOS)
            image.save(
                temporary_path,
                format="WEBP",
                quality=THUMBNAIL_QUALITY,
                method=4,
            )
        final_stat = candidate.path.stat()
        if final_stat.st_size != candidate.file_size or not _same_timestamp(
            final_stat.st_mtime,
            candidate.file_modified_at,
        ):
            return "stale"
        os.replace(temporary_path, target)
        temporary_path = None
        return "generated"
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _generation_result(
    *,
    total: int,
    processed: int,
    generated: int,
    cached: int,
    stale: int,
    failed: int,
    errors: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "unique_content_count": total,
        "processed_content_count": processed,
        "generated_count": generated,
        "cached_count": cached,
        "stale_count": stale,
        "failed_count": failed,
        "error_count": failed,
        "errors": errors,
        "spec_version": THUMBNAIL_SPEC_VERSION,
    }


def generate_thumbnail_batch(
    candidates: list[ThumbnailCandidate],
    *,
    checkpoint: Callable[[], None],
    progress: Callable[[int, int, int], None],
) -> dict[str, object]:
    total = len(candidates)
    processed = generated = cached = stale = failed = 0
    errors: list[dict[str, object]] = []
    checkpoint()
    if not candidates:
        return _generation_result(
            total=0,
            processed=0,
            generated=0,
            cached=0,
            stale=0,
            failed=0,
            errors=[],
        )

    executor = ThreadPoolExecutor(
        max_workers=min(THUMBNAIL_WORKERS, total),
        thread_name_prefix="thumbnail",
    )
    pending: dict[Future[str], ThumbnailCandidate] = {}
    iterator = iter(candidates)

    def submit_next() -> bool:
        try:
            candidate = next(iterator)
        except StopIteration:
            return False
        pending[executor.submit(generate_thumbnail, candidate)] = candidate
        return True

    try:
        for _ in range(min(THUMBNAIL_WORKERS, total)):
            submit_next()
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                candidate = pending.pop(future)
                try:
                    outcome = future.result()
                except Exception as exc:
                    failed += 1
                    if len(errors) < MAX_ERRORS:
                        errors.append(
                            {
                                "sample_id": candidate.sample_id,
                                "message": str(exc)[:500],
                                "type": type(exc).__name__,
                            }
                        )
                else:
                    if outcome == "generated":
                        generated += 1
                    elif outcome == "cached":
                        cached += 1
                    else:
                        stale += 1
                processed += 1
                progress(processed, total, failed)
                checkpoint()
                submit_next()
    except Exception as exc:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        stopped = ThumbnailGenerationStopped(
            _generation_result(
                total=total,
                processed=processed,
                generated=generated,
                cached=cached,
                stale=stale,
                failed=failed,
                errors=errors,
            )
        )
        raise stopped from exc
    else:
        executor.shutdown(wait=True)

    return _generation_result(
        total=total,
        processed=processed,
        generated=generated,
        cached=cached,
        stale=stale,
        failed=failed,
        errors=errors,
    )
