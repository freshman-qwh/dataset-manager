import csv
import json
from pathlib import Path, PureWindowsPath

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.sample import Sample
from app.schemas.metadata_import import MetadataImportRequest, MetadataImportResult
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import _clean_tag_names, _get_or_create_tag, _validate_review_status
from app.utils.paths import resolve_local_path

RESERVED_COLUMNS = {
    "sample_id",
    "relative_path",
    "absolute_path",
    "filename",
    "file_hash",
    "tags",
    "split",
    "review_status",
    "notes",
}
SUPPORTED_MATCH_FIELDS = {"sample_id", "relative_path", "absolute_path", "filename", "file_hash"}


def import_metadata(session: Session, dataset_id: int, payload: MetadataImportRequest) -> MetadataImportResult:
    dataset = get_dataset_or_404(session, dataset_id)
    source = resolve_local_path(payload.file_path)
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Metadata file does not exist: {source}")
    if source.suffix.lower() not in {".csv", ".json"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV and JSON metadata files are supported.")
    if payload.match_by not in SUPPORTED_MATCH_FIELDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported match_by field: {payload.match_by}")

    rows = _load_rows(source)
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset_id)).all()
    if not samples:
        return MetadataImportResult(
            dataset_id=dataset_id,
            source_path=str(source),
            total_rows=len(rows),
            matched=0,
            updated=0,
            skipped=len(rows),
            errors=["Dataset has no registered samples. Run scan before importing metadata."],
        )

    sample_index = _build_sample_index(samples, payload.match_by)
    relative_index = _build_sample_index(samples, "relative_path")
    filename_index = _build_filename_index(samples)

    matched = 0
    updated = 0
    errors: list[str] = []

    for row_number, row in enumerate(rows, start=1):
        key = str(row.get(payload.match_by, "")).strip()
        if not key:
            errors.append(f"Row {row_number}: missing {payload.match_by}")
            continue
        sample = _match_sample(sample_index, payload.match_by, key)
        if not sample and payload.match_by == "absolute_path":
            sample = _match_absolute_by_dataset_root(relative_index, key, dataset.root_path)
        if not sample:
            errors.append(_build_no_match_error(row_number, payload.match_by, key, dataset.root_path, filename_index))
            continue

        matched += 1
        _apply_row(session, dataset_id, sample, row, payload.tag_column, payload.replace_tags)
        session.add(sample)
        updated += 1

    session.commit()
    return MetadataImportResult(
        dataset_id=dataset_id,
        source_path=str(source),
        total_rows=len(rows),
        matched=matched,
        updated=updated,
        skipped=len(rows) - matched,
        errors=errors[:50],
    )


def _load_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".csv":
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV metadata must include a header row.")
                return [dict(row) for row in reader]
        except OSError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unable to read CSV metadata: {exc}") from exc

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            parsed = json.load(file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON metadata: {exc.msg}") from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unable to read JSON metadata: {exc}") from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("samples"), list):
        parsed = parsed["samples"]
    if not isinstance(parsed, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON metadata must be a list or contain samples[].")
    rows = [row for row in parsed if isinstance(row, dict)]
    if len(rows) != len(parsed):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Every JSON metadata row must be an object.")
    return rows


def _build_sample_index(samples: list[Sample], match_by: str) -> dict[str, Sample]:
    index: dict[str, Sample] = {}
    for sample in samples:
        value = sample.id if match_by == "sample_id" else getattr(sample, match_by)
        if value is not None:
            for key in _normalize_match_keys(match_by, value):
                index.setdefault(key, sample)
    return index


def _build_filename_index(samples: list[Sample]) -> dict[str, list[Sample]]:
    index: dict[str, list[Sample]] = {}
    for sample in samples:
        index.setdefault(sample.filename.casefold(), []).append(sample)
    return index


def _match_sample(index: dict[str, Sample], match_by: str, value: object) -> Sample | None:
    for key in _normalize_match_keys(match_by, value):
        sample = index.get(key)
        if sample:
            return sample
    return None


def _normalize_match_keys(match_by: str, value: object) -> list[str]:
    text = str(value).strip()
    text = text.strip('"').strip("'")
    if match_by == "absolute_path":
        variants = {text, text.replace("\\", "/"), text.replace("/", "\\")}
        try:
            variants.add(str(Path(text).expanduser().resolve(strict=False)))
        except (OSError, RuntimeError):
            variants.add(str(Path(text).expanduser()))
        try:
            windows_path = PureWindowsPath(text)
            variants.add(str(windows_path))
            variants.add(windows_path.as_posix())
        except (OSError, RuntimeError):
            pass
        return _unique_keys(_normalize_absolute_key(item) for item in variants)
    if match_by == "relative_path":
        normalized = text.replace("\\", "/").removeprefix("./")
        return _unique_keys([normalized, normalized.casefold()])
    if match_by == "filename":
        return [text.casefold()]
    return [text]


def _normalize_absolute_key(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()


def _unique_keys(values) -> list[str]:
    keys: list[str] = []
    seen = set()
    for value in values:
        key = str(value).strip()
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _match_absolute_by_dataset_root(
    relative_index: dict[str, Sample],
    absolute_path: str,
    dataset_root: str | None,
) -> Sample | None:
    if not dataset_root:
        return None
    try:
        path = Path(absolute_path).expanduser().resolve(strict=False)
        root = Path(dataset_root).expanduser().resolve(strict=False)
        relative = path.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    return _match_sample(relative_index, "relative_path", relative)


def _build_no_match_error(
    row_number: int,
    match_by: str,
    key: str,
    dataset_root: str | None,
    filename_index: dict[str, list[Sample]],
) -> str:
    if match_by != "absolute_path":
        return f"Row {row_number}: no sample matched {match_by}={key}"

    normalized = _normalize_match_keys("absolute_path", key)[0] if key else ""
    detail = f"Row {row_number}: no sample matched absolute_path={key}; normalized={normalized}"
    if dataset_root:
        try:
            path = Path(key).expanduser().resolve(strict=False)
            root = Path(dataset_root).expanduser().resolve(strict=False)
            relative = path.relative_to(root).as_posix()
            detail += f"; relative_to_root={relative}"
        except (OSError, RuntimeError, ValueError):
            detail += f"; dataset_root={dataset_root}"

    filename = Path(key).name.casefold()
    candidates = filename_index.get(filename, [])
    if candidates:
        candidate_paths = ", ".join(sample.absolute_path for sample in candidates[:3])
        detail += f"; same filename exists at: {candidate_paths}"
    return detail


def _apply_row(
    session: Session,
    dataset_id: int,
    sample: Sample,
    row: dict[str, object],
    tag_column: str,
    replace_tags: bool,
) -> None:
    if "split" in row:
        split = str(row.get("split") or "").strip()
        sample.split = split or None
    if "review_status" in row:
        review_status = str(row.get("review_status") or "").strip()
        if review_status:
            sample.review_status = _validate_review_status(review_status)
    if "notes" in row:
        notes = str(row.get("notes") or "").strip()
        sample.notes = notes or None

    raw_tags = row.get(tag_column)
    if raw_tags is not None:
        tag_names = _tags_from_value(raw_tags)
        tags = [_get_or_create_tag(session, dataset_id, name) for name in tag_names]
        if replace_tags:
            sample.tags = tags
        else:
            existing = {tag.name.casefold() for tag in sample.tags}
            sample.tags.extend([tag for tag in tags if tag.name.casefold() not in existing])

    metadata = _loads_metadata(sample.metadata_json)
    for key, value in row.items():
        if key == tag_column or key in RESERVED_COLUMNS:
            continue
        metadata[key] = value
    sample.metadata_json = json.dumps(metadata, ensure_ascii=False)
    sample.updated_at = utc_now()


def _tags_from_value(value: object) -> list[str]:
    if isinstance(value, list):
        return _clean_tag_names([str(item) for item in value])
    return _clean_tag_names(str(value).replace(";", ",").split(","))


def _loads_metadata(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
