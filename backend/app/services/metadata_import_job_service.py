from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.sample import Sample
from app.schemas.job import JobCreate, JobRead
from app.schemas.metadata_import import (
    MetadataImportJobCreateRequest,
    MetadataImportJobCreateResponse,
    MetadataImportJobParameters,
    MetadataImportRequest,
    MetadataImportRollbackJobCreateResponse,
)
from app.services import dataset_service, job_service, metadata_import_service
from app.services.job_runner import JobCancelled, JobContext, JobFailed, JobInterrupted
from app.services.sample_service import _get_or_create_tag


METADATA_IMPORT_JOB_TYPE = "metadata.import"
METADATA_IMPORT_ROLLBACK_JOB_TYPE = "metadata.import.rollback"
IMPORT_BATCH_SIZE = 100
ROLLBACK_BATCH_SIZE = 100
JOURNAL_VERSION = 1
JOURNAL_FILENAME = "metadata-import-rollback.jsonl"


def create_metadata_import_job(
    session: Session,
    dataset_id: int,
    payload: MetadataImportJobCreateRequest,
) -> MetadataImportJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    preview_payload = MetadataImportRequest(
        file_path=payload.file_path,
        match_by=payload.match_by,
        tag_column=payload.tag_column,
        replace_tags=payload.replace_tags,
        dry_run=True,
        expected_source_sha256=payload.expected_source_sha256,
    )
    plan = metadata_import_service.prepare_metadata_import(
        session,
        dataset_id,
        preview_payload,
    )
    if not plan.operations:
        raise job_service.JobStateError(
            "Metadata import preview does not contain any valid updates."
        )

    request_payload = {
        "file_path": str(plan.source),
        "match_by": payload.match_by,
        "tag_column": payload.tag_column,
        "replace_tags": payload.replace_tags,
        "expected_source_sha256": plan.source_sha256,
        "source_size_bytes": len(plan.source_bytes),
        "planned_updates": len(plan.operations),
        "preview_error_count": len(
            [issue for issue in plan.issues if issue.severity == "error"]
        ),
    }
    request_fingerprint = sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    parameters = MetadataImportJobParameters(
        **request_payload,
        request_fingerprint=request_fingerprint,
    ).model_dump(mode="json")

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=METADATA_IMPORT_JOB_TYPE,
        dataset_id=dataset_id,
        parameter_match=("request_fingerprint", request_fingerprint),
    )
    if active is not None:
        session.commit()
        return MetadataImportJobCreateResponse(job=active, created=False)

    created = job_service.create_job(
        session,
        JobCreate(
            job_type=METADATA_IMPORT_JOB_TYPE,
            title=f"导入元数据：{dataset.name}",
            dataset_id=dataset_id,
            parameters=parameters,
            progress_total=len(plan.operations),
        ),
    )
    return MetadataImportJobCreateResponse(job=created, created=True)


def run_metadata_import_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    try:
        snapshot = MetadataImportJobParameters.model_validate(parameters)
    except ValidationError as exc:
        raise job_service.JobStateError(
            f"Invalid metadata import parameter snapshot: {exc}"
        ) from exc

    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id is None:
            raise job_service.JobStateError(
                "A metadata.import job requires dataset_id."
            )
        dataset_id = job.dataset_id
        journal_job_id = _root_retry_job_id(session, job)

    context.report_progress(current=0, stage="prechecking")
    with Session(context.engine) as session:
        plan = metadata_import_service.prepare_metadata_import(
            session,
            dataset_id,
            MetadataImportRequest(
                file_path=snapshot.file_path,
                match_by=snapshot.match_by,
                tag_column=snapshot.tag_column,
                replace_tags=snapshot.replace_tags,
                dry_run=False,
                expected_source_sha256=snapshot.expected_source_sha256,
            ),
        )
    if len(plan.source_bytes) != snapshot.source_size_bytes:
        raise job_service.JobStateError(
            "Metadata source size changed after the task was created."
        )
    if len(plan.operations) != snapshot.planned_updates:
        raise job_service.JobStateError(
            "Metadata import targets changed after preview. Run preview again."
        )

    journal = _RollbackJournal(
        _journal_path(journal_job_id),
        journal_job_id=journal_job_id,
        dataset_id=dataset_id,
        source_sha256=snapshot.expected_source_sha256.lower(),
        request_fingerprint=snapshot.request_fingerprint,
    )
    journal.initialize()
    updated = 0
    batches_committed = 0

    def result() -> dict[str, object]:
        return {
            "source_job_id": journal_job_id,
            "source_sha256": snapshot.expected_source_sha256.lower(),
            "planned_updates": snapshot.planned_updates,
            "updated": updated,
            "unique_samples_changed": journal.entry_count,
            "batches_committed": batches_committed,
            "preview_error_count": snapshot.preview_error_count,
            "rollback_available": journal.entry_count > 0,
        }

    try:
        for offset in range(0, len(plan.operations), IMPORT_BATCH_SIZE):
            context.checkpoint()
            batch = plan.operations[offset : offset + IMPORT_BATCH_SIZE]
            sample_ids = sorted({operation.sample_id for operation in batch})
            with Session(context.engine) as session:
                samples = {
                    sample.id: sample
                    for sample in session.exec(
                        select(Sample)
                        .where(
                            Sample.dataset_id == dataset_id,
                            Sample.id.in_(sample_ids),
                        )
                        .options(selectinload(Sample.tags))
                    ).all()
                }
                if len(samples) != len(sample_ids):
                    raise job_service.JobStateError(
                        "A metadata import target disappeared after preview."
                    )
                journal.append_missing(samples.values())
                for operation in batch:
                    sample = samples[operation.sample_id]
                    metadata_import_service.apply_metadata_row(
                        session,
                        dataset_id,
                        sample,
                        operation.row,
                        snapshot.tag_column,
                        snapshot.replace_tags,
                    )
                    session.add(sample)
                session.commit()
            updated += len(batch)
            batches_committed += 1
            context.report_progress(
                current=updated,
                total=snapshot.planned_updates,
                stage="writing_metadata",
                error_count=snapshot.preview_error_count,
            )
        context.report_progress(
            current=updated,
            total=snapshot.planned_updates,
            stage="finalizing",
            error_count=snapshot.preview_error_count,
        )
        context.checkpoint()
    except JobCancelled as exc:
        raise JobCancelled(str(exc), result=result()) from exc
    except JobInterrupted as exc:
        raise JobInterrupted(str(exc), result=result()) from exc
    except Exception as exc:
        raise JobFailed(str(exc), result=result()) from exc
    return result()


def create_metadata_import_rollback_job(
    session: Session,
    source_job_id: int,
) -> MetadataImportRollbackJobCreateResponse:
    source_job = job_service.get_job(session, source_job_id)
    if source_job.job_type != METADATA_IMPORT_JOB_TYPE:
        raise job_service.JobStateError(
            "Only metadata import jobs can create metadata rollback jobs."
        )
    if source_job.status not in job_service.TERMINAL_STATUSES:
        raise job_service.JobStateError(
            "Metadata import rollback is available only after the import task stops."
        )
    if source_job.dataset_id is None:
        raise job_service.JobStateError("The metadata import job has no dataset.")
    journal_job_id = _root_retry_job_id(session, source_job)
    journal = _RollbackJournal.load(_journal_path(journal_job_id))
    if journal.dataset_id != source_job.dataset_id:
        raise job_service.JobStateError("Metadata rollback journal dataset mismatch.")
    if journal.entry_count == 0:
        raise job_service.JobStateError(
            "The metadata import task did not commit any recoverable changes."
        )

    fingerprint = sha256(
        f"{journal_job_id}:{journal.entry_count}:{journal.source_sha256}".encode("utf-8")
    ).hexdigest()
    parameters = {
        "source_job_id": source_job_id,
        "journal_job_id": journal_job_id,
        "entry_count": journal.entry_count,
        "source_sha256": journal.source_sha256,
        "request_fingerprint": fingerprint,
    }
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=METADATA_IMPORT_ROLLBACK_JOB_TYPE,
        dataset_id=source_job.dataset_id,
        parameter_match=("request_fingerprint", fingerprint),
    )
    if active is not None:
        session.commit()
        return MetadataImportRollbackJobCreateResponse(job=active, created=False)

    dataset = dataset_service.get_dataset_or_404(session, source_job.dataset_id)
    created = job_service.create_job(
        session,
        JobCreate(
            job_type=METADATA_IMPORT_ROLLBACK_JOB_TYPE,
            title=f"回滚元数据导入：{dataset.name}",
            dataset_id=source_job.dataset_id,
            parameters=parameters,
            progress_total=journal.entry_count,
        ),
    )
    return MetadataImportRollbackJobCreateResponse(job=created, created=True)


def run_metadata_import_rollback_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    journal_job_id = _positive_int(parameters.get("journal_job_id"), "journal_job_id")
    expected_count = _positive_int(parameters.get("entry_count"), "entry_count")
    journal = _RollbackJournal.load(_journal_path(journal_job_id))
    if journal.entry_count != expected_count:
        raise job_service.JobStateError(
            "Metadata rollback journal changed after the task was created."
        )
    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id != journal.dataset_id:
            raise job_service.JobStateError("Metadata rollback dataset mismatch.")

    restored = 0
    missing = 0
    batches_committed = 0

    def result() -> dict[str, object]:
        return {
            "source_job_id": journal_job_id,
            "restored": restored,
            "missing": missing,
            "batches_committed": batches_committed,
        }

    try:
        context.report_progress(current=0, stage="prechecking")
        entries = list(journal.entries.values())
        for offset in range(0, len(entries), ROLLBACK_BATCH_SIZE):
            context.checkpoint()
            batch = entries[offset : offset + ROLLBACK_BATCH_SIZE]
            sample_ids = [int(entry["sample_id"]) for entry in batch]
            with Session(context.engine) as session:
                samples = {
                    sample.id: sample
                    for sample in session.exec(
                        select(Sample)
                        .where(
                            Sample.dataset_id == journal.dataset_id,
                            Sample.id.in_(sample_ids),
                        )
                        .options(selectinload(Sample.tags))
                    ).all()
                }
                for entry in batch:
                    sample = samples.get(int(entry["sample_id"]))
                    if sample is None:
                        missing += 1
                        continue
                    _restore_sample(session, journal.dataset_id, sample, entry)
                    session.add(sample)
                    restored += 1
                session.commit()
            batches_committed += 1
            context.report_progress(
                current=min(offset + len(batch), len(entries)),
                total=len(entries),
                stage="rolling_back_metadata",
                error_count=missing,
            )
        context.report_progress(
            current=len(entries),
            total=len(entries),
            stage="finalizing",
            error_count=missing,
        )
    except JobCancelled as exc:
        raise JobCancelled(str(exc), result=result()) from exc
    except JobInterrupted as exc:
        raise JobInterrupted(str(exc), result=result()) from exc
    except Exception as exc:
        raise JobFailed(str(exc), result=result()) from exc
    return result()


class _RollbackJournal:
    def __init__(
        self,
        path: Path,
        *,
        journal_job_id: int,
        dataset_id: int,
        source_sha256: str,
        request_fingerprint: str,
    ) -> None:
        self.path = path
        self.journal_job_id = journal_job_id
        self.dataset_id = dataset_id
        self.source_sha256 = source_sha256
        self.request_fingerprint = request_fingerprint
        self.entries: dict[int, dict[str, object]] = {}

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def initialize(self) -> None:
        if self.path.exists():
            loaded = self.load(self.path)
            if (
                loaded.journal_job_id != self.journal_job_id
                or loaded.dataset_id != self.dataset_id
                or loaded.source_sha256 != self.source_sha256
                or loaded.request_fingerprint != self.request_fingerprint
            ):
                raise job_service.JobStateError(
                    "Metadata rollback journal does not match this task."
                )
            self.entries = loaded.entries
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "kind": "header",
            "version": JOURNAL_VERSION,
            "journal_job_id": self.journal_job_id,
            "dataset_id": self.dataset_id,
            "source_sha256": self.source_sha256,
            "request_fingerprint": self.request_fingerprint,
        }
        _append_json_lines(self.path, [header], exclusive=True)

    def append_missing(self, samples) -> None:
        next_entries: list[dict[str, object]] = []
        for sample in samples:
            if sample.id is None or sample.id in self.entries:
                continue
            entry = {
                "kind": "sample",
                "sample_id": sample.id,
                "split": sample.split,
                "review_status": sample.review_status,
                "notes": sample.notes,
                "metadata_json": sample.metadata_json,
                "updated_at": sample.updated_at.isoformat(),
                "tag_names": sorted(tag.name for tag in sample.tags),
            }
            next_entries.append(entry)
        if not next_entries:
            return
        _append_json_lines(self.path, next_entries)
        for entry in next_entries:
            self.entries[int(entry["sample_id"])] = entry

    @classmethod
    def load(cls, path: Path) -> _RollbackJournal:
        records = _read_json_lines(path)
        if not records or records[0].get("kind") != "header":
            raise job_service.JobStateError("Metadata rollback journal is invalid.")
        header = records[0]
        if header.get("version") != JOURNAL_VERSION:
            raise job_service.JobStateError(
                "Metadata rollback journal version is unsupported."
            )
        journal = cls(
            path,
            journal_job_id=int(header["journal_job_id"]),
            dataset_id=int(header["dataset_id"]),
            source_sha256=str(header["source_sha256"]),
            request_fingerprint=str(header["request_fingerprint"]),
        )
        for record in records[1:]:
            if record.get("kind") != "sample":
                raise job_service.JobStateError(
                    "Metadata rollback journal contains an invalid record."
                )
            journal.entries[int(record["sample_id"])] = record
        return journal


def _root_retry_job_id(session: Session, job: JobRead) -> int:
    current = job
    visited = {current.id}
    while current.retry_of_id is not None:
        if current.retry_of_id in visited:
            raise job_service.JobStateError("Job retry lineage contains a cycle.")
        visited.add(current.retry_of_id)
        current = job_service.get_job(session, current.retry_of_id)
        if current.job_type != METADATA_IMPORT_JOB_TYPE:
            raise job_service.JobStateError("Metadata import retry lineage is invalid.")
    return current.id


def _journal_path(job_id: int) -> Path:
    root = (get_settings().storage_root / "job-recovery").resolve()
    job_directory = (root / f"job-{job_id}").resolve()
    if job_directory.parent != root:
        raise ValueError("Metadata recovery path escaped its storage root.")
    return job_directory / JOURNAL_FILENAME


def _append_json_lines(
    path: Path,
    records: list[dict[str, object]],
    *,
    exclusive: bool = False,
) -> None:
    mode = "x" if exclusive else "a"
    try:
        with path.open(mode, encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise job_service.JobStateError(
            f"Unable to persist metadata rollback journal: {exc}"
        ) from exc


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise job_service.JobStateError(
            "Metadata rollback journal is not available."
        ) from exc
    records: list[dict[str, object]] = []
    for index, line in enumerate(raw_lines):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            if index == len(raw_lines) - 1:
                break
            raise job_service.JobStateError(
                "Metadata rollback journal is corrupted."
            ) from exc
        if not isinstance(parsed, dict):
            raise job_service.JobStateError(
                "Metadata rollback journal contains a non-object record."
            )
        records.append(parsed)
    return records


def _restore_sample(
    session: Session,
    dataset_id: int,
    sample: Sample,
    entry: dict[str, object],
) -> None:
    sample.split = _optional_string(entry.get("split"))
    sample.review_status = str(entry["review_status"])
    sample.notes = _optional_string(entry.get("notes"))
    sample.metadata_json = _optional_string(entry.get("metadata_json"))
    raw_tag_names = entry.get("tag_names")
    if not isinstance(raw_tag_names, list) or not all(
        isinstance(name, str) for name in raw_tag_names
    ):
        raise job_service.JobStateError(
            "Metadata rollback journal has invalid tag names."
        )
    sample.tags = [
        _get_or_create_tag(session, dataset_id, name) for name in raw_tag_names
    ]
    sample.updated_at = datetime.fromisoformat(str(entry["updated_at"]))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise job_service.JobStateError(f"{name} must be a positive integer.")
    return value
