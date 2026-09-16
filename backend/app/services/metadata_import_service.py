import csv
from dataclasses import dataclass
from hashlib import sha256
import io
import json
from pathlib import Path, PureWindowsPath

from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.sample import Sample
from app.schemas.metadata_import import (
    MetadataImportIssue,
    MetadataImportRequest,
    MetadataImportResult,
)
from app.services.dataset_service import get_dataset_or_404
from app.services.dataset_revision_service import bump_dataset_revision
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


@dataclass(frozen=True)
class MetadataImportOperation:
    sample_id: int
    row: dict[str, object]


@dataclass(frozen=True)
class MetadataImportPlan:
    dataset_id: int
    source: Path
    source_bytes: bytes
    source_sha256: str
    payload: MetadataImportRequest
    total_rows: int
    matched: int
    issues: list[MetadataImportIssue]
    operations: list[MetadataImportOperation]


def import_metadata(session: Session, dataset_id: int, payload: MetadataImportRequest) -> MetadataImportResult:
    plan = prepare_metadata_import(session, dataset_id, payload)
    updated = 0
    if not payload.dry_run:
        samples = {
            sample.id: sample
            for sample in session.exec(
                select(Sample)
                .where(
                    Sample.dataset_id == dataset_id,
                    Sample.id.in_([operation.sample_id for operation in plan.operations]),
                )
                .options(selectinload(Sample.tags))
            ).all()
        }
        for operation in plan.operations:
            sample = samples.get(operation.sample_id)
            if sample is None:
                continue
            apply_metadata_row(
                session,
                dataset_id,
                sample,
                operation.row,
                payload.tag_column,
                payload.replace_tags,
            )
            session.add(sample)
            updated += 1
        if updated:
            bump_dataset_revision(session, dataset_id)
        session.commit()
    return metadata_import_result(plan, updated=updated)


def prepare_metadata_import(
    session: Session,
    dataset_id: int,
    payload: MetadataImportRequest,
) -> MetadataImportPlan:
    dataset = get_dataset_or_404(session, dataset_id)
    source = resolve_local_path(payload.file_path)
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Metadata file does not exist: {source}")
    if source.suffix.lower() not in {".csv", ".json"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV and JSON metadata files are supported.")
    if payload.match_by not in SUPPORTED_MATCH_FIELDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported match_by field: {payload.match_by}")

    source_bytes = _read_source(source)
    source_sha256 = sha256(source_bytes).hexdigest()
    if (
        payload.expected_source_sha256 is not None
        and payload.expected_source_sha256.casefold() != source_sha256
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Metadata source changed after preview. Run preview again before importing.",
        )
    rows = _load_rows(source, source_bytes)
    samples = session.exec(
        select(Sample)
        .where(Sample.dataset_id == dataset_id)
        .options(selectinload(Sample.tags))
    ).all()
    if not samples:
        issue = _issue(
            "NO_SAMPLES",
            "Dataset has no registered samples. Run scan before importing metadata.",
        )
        return MetadataImportPlan(
            dataset_id=dataset_id,
            source=source,
            source_bytes=source_bytes,
            source_sha256=source_sha256,
            payload=payload,
            total_rows=len(rows),
            matched=0,
            issues=[issue],
            operations=[],
        )

    sample_index = _build_sample_index(samples, payload.match_by)
    relative_index = _build_sample_index(samples, "relative_path")
    filename_index = _build_filename_index(samples)

    matched = 0
    issues: list[MetadataImportIssue] = []
    operations: list[MetadataImportOperation] = []

    for row_number, row in enumerate(rows, start=1):
        key = str(row.get(payload.match_by, "")).strip()
        if not key:
            issues.append(
                _issue(
                    "MISSING_MATCH_VALUE",
                    f"Row {row_number}: missing {payload.match_by}",
                    row_number=row_number,
                )
            )
            continue
        sample, ambiguous = _match_sample(sample_index, payload.match_by, key)
        if not sample and not ambiguous and payload.match_by == "absolute_path":
            sample, ambiguous = _match_absolute_by_dataset_root(
                relative_index,
                key,
                dataset.root_path,
            )
        if ambiguous:
            issues.append(
                _issue(
                    "AMBIGUOUS_SAMPLE_MATCH",
                    f"Row {row_number}: multiple samples matched {payload.match_by}={key}",
                    row_number=row_number,
                    match_value=key,
                )
            )
            continue
        if not sample:
            issues.append(
                _issue(
                    "SAMPLE_NOT_FOUND",
                    _build_no_match_error(
                        row_number,
                        payload.match_by,
                        key,
                        dataset.root_path,
                        filename_index,
                    ),
                    row_number=row_number,
                    match_value=key,
                )
            )
            continue

        matched += 1
        row_issue = _validate_row(row, row_number, key)
        if row_issue is not None:
            issues.append(row_issue)
            continue
        if sample.id is None:
            raise RuntimeError("A persisted metadata import sample must have an id.")
        operations.append(MetadataImportOperation(sample_id=sample.id, row=row))

    return MetadataImportPlan(
        dataset_id=dataset_id,
        source=source,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        payload=payload,
        total_rows=len(rows),
        matched=matched,
        issues=issues,
        operations=operations,
    )


def _read_source(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to read metadata: {exc}",
        ) from exc


def _load_rows(path: Path, source_bytes: bytes) -> list[dict[str, object]]:
    try:
        source_text = source_bytes.decode(
            "utf-8-sig",
            errors="replace" if path.suffix.lower() == ".csv" else "strict",
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON metadata must be encoded as UTF-8.",
        ) from exc
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(source_text, newline=""))
        if not reader.fieldnames:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV metadata must include a header row.")
        return [dict(row) for row in reader]

    try:
        parsed = json.loads(source_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON metadata: {exc.msg}") from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("samples"), list):
        parsed = parsed["samples"]
    if not isinstance(parsed, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON metadata must be a list or contain samples[].")
    rows = [row for row in parsed if isinstance(row, dict)]
    if len(rows) != len(parsed):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Every JSON metadata row must be an object.")
    return rows


def _build_sample_index(samples: list[Sample], match_by: str) -> dict[str, list[Sample]]:
    index: dict[str, list[Sample]] = {}
    for sample in samples:
        value = sample.id if match_by == "sample_id" else getattr(sample, match_by)
        if value is not None:
            for key in _normalize_match_keys(match_by, value):
                matches = index.setdefault(key, [])
                if all(existing.id != sample.id for existing in matches):
                    matches.append(sample)
    return index


def _build_filename_index(samples: list[Sample]) -> dict[str, list[Sample]]:
    index: dict[str, list[Sample]] = {}
    for sample in samples:
        index.setdefault(sample.filename.casefold(), []).append(sample)
    return index


def _match_sample(
    index: dict[str, list[Sample]],
    match_by: str,
    value: object,
) -> tuple[Sample | None, bool]:
    matches: dict[int, Sample] = {}
    for key in _normalize_match_keys(match_by, value):
        for sample in index.get(key, []):
            if sample.id is not None:
                matches[sample.id] = sample
    if len(matches) == 1:
        return next(iter(matches.values())), False
    return None, len(matches) > 1


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
    relative_index: dict[str, list[Sample]],
    absolute_path: str,
    dataset_root: str | None,
) -> tuple[Sample | None, bool]:
    if not dataset_root:
        return None, False
    try:
        path = Path(absolute_path).expanduser().resolve(strict=False)
        root = Path(dataset_root).expanduser().resolve(strict=False)
        relative = path.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None, False
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


def _validate_row(
    row: dict[str, object],
    row_number: int,
    match_value: str,
) -> MetadataImportIssue | None:
    if "review_status" not in row:
        return None
    review_status = str(row.get("review_status") or "").strip()
    if not review_status:
        return None
    try:
        _validate_review_status(review_status)
    except HTTPException as exc:
        return _issue(
            "INVALID_REVIEW_STATUS",
            f"Row {row_number}: {exc.detail}",
            row_number=row_number,
            match_value=match_value,
        )
    return None


def _issue(
    code: str,
    message: str,
    *,
    row_number: int | None = None,
    match_value: str | None = None,
) -> MetadataImportIssue:
    return MetadataImportIssue(
        severity="error",
        code=code,
        message=message,
        row_number=row_number,
        match_value=match_value,
    )


def metadata_import_result(
    plan: MetadataImportPlan,
    *,
    updated: int,
) -> MetadataImportResult:
    error_issues = [issue for issue in plan.issues if issue.severity == "error"]
    return MetadataImportResult(
        dataset_id=plan.dataset_id,
        source_path=str(plan.source),
        source_size_bytes=len(plan.source_bytes),
        source_sha256=plan.source_sha256,
        dry_run=plan.payload.dry_run,
        total_rows=plan.total_rows,
        matched=plan.matched,
        planned_updates=len(plan.operations),
        updated=updated,
        skipped=plan.total_rows - len(plan.operations),
        error_count=len(error_issues),
        issues=plan.issues[:100],
        errors=[issue.message for issue in error_issues[:50]],
    )


def apply_metadata_row(
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
