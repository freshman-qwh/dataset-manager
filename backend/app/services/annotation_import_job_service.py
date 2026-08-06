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
from app.models.annotation import Annotation
from app.models.sample import Sample
from app.schemas.annotation import AnnotationCreate, AnnotationReplaceRequest
from app.schemas.annotation_import import (
    LabelmeImportJobCreateRequest,
    LabelmeImportJobCreateResponse,
    LabelmeImportJobParameters,
    LabelmeImportRequest,
    LabelmeImportRollbackJobCreateResponse,
)
from app.schemas.job import JobCreate, JobRead
from app.services import annotation_import_service, annotation_service, dataset_service, job_service
from app.services.job_runner import JobCancelled, JobContext, JobFailed, JobInterrupted
from app.services.sample_service import _get_or_create_tag


LABELME_IMPORT_JOB_TYPE = "annotation.import.labelme"
LABELME_IMPORT_ROLLBACK_JOB_TYPE = "annotation.import.labelme.rollback"
IMPORT_BATCH_SIZE = 25
ROLLBACK_BATCH_SIZE = 25
JOURNAL_VERSION = 1
JOURNAL_FILENAME = "labelme-import-rollback.jsonl"


def create_labelme_import_job(
    session: Session,
    dataset_id: int,
    payload: LabelmeImportJobCreateRequest,
) -> LabelmeImportJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    preview_payload = LabelmeImportRequest(
        path=payload.path,
        mode=payload.mode,
        sample_id=payload.sample_id,
        strategy=payload.strategy,
        dry_run=True,
        sync_sample_tags=payload.sync_sample_tags,
        expected_source_sha256=payload.expected_source_sha256,
    )
    plan = annotation_import_service.prepare_labelme_import(session, dataset_id, preview_payload)
    if plan.plan_fingerprint != payload.expected_plan_fingerprint.lower():
        raise job_service.JobStateError("LabelMe import targets changed after preview. Run preview again.")
    if not plan.operations:
        raise job_service.JobStateError("LabelMe import preview does not contain any valid sample updates.")

    request_payload = {
        "path": str(plan.source),
        "mode": payload.mode,
        "sample_id": payload.sample_id,
        "strategy": payload.strategy,
        "sync_sample_tags": payload.sync_sample_tags,
        "expected_source_sha256": plan.source_sha256,
        "expected_plan_fingerprint": plan.plan_fingerprint,
        "source_size_bytes": plan.source_size_bytes,
        "checked_files": plan.checked_files,
        "planned_samples": len(plan.operations),
        "planned_annotations": sum(len(item.annotations) for item in plan.operations),
        "preview_error_count": len(plan.errors),
    }
    request_fingerprint = sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    parameters = LabelmeImportJobParameters(
        **request_payload,
        request_fingerprint=request_fingerprint,
    ).model_dump(mode="json")

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=LABELME_IMPORT_JOB_TYPE,
        dataset_id=dataset_id,
        parameter_match=("request_fingerprint", request_fingerprint),
    )
    if active is not None:
        session.commit()
        return LabelmeImportJobCreateResponse(job=active, created=False)
    created = job_service.create_job(
        session,
        JobCreate(
            job_type=LABELME_IMPORT_JOB_TYPE,
            title=f"导入 LabelMe 标注：{dataset.name}",
            dataset_id=dataset_id,
            parameters=parameters,
            progress_total=len(plan.operations),
        ),
    )
    return LabelmeImportJobCreateResponse(job=created, created=True)


def run_labelme_import_job(context: JobContext, parameters: dict[str, object]) -> dict[str, object]:
    try:
        snapshot = LabelmeImportJobParameters.model_validate(parameters)
    except ValidationError as exc:
        raise job_service.JobStateError(f"Invalid LabelMe import parameter snapshot: {exc}") from exc

    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id is None:
            raise job_service.JobStateError("A LabelMe import job requires dataset_id.")
        dataset_id = job.dataset_id
        journal_job_id = _root_retry_job_id(session, job)

    context.report_progress(current=0, stage="parsing_labelme")
    with Session(context.engine) as session:
        plan = annotation_import_service.prepare_labelme_import(
            session,
            dataset_id,
            LabelmeImportRequest(
                path=snapshot.path,
                mode=snapshot.mode,
                sample_id=snapshot.sample_id,
                strategy=snapshot.strategy,
                dry_run=True,
                sync_sample_tags=snapshot.sync_sample_tags,
                expected_source_sha256=snapshot.expected_source_sha256,
            ),
        )
    if plan.source_size_bytes != snapshot.source_size_bytes or plan.checked_files != snapshot.checked_files:
        raise job_service.JobStateError("LabelMe source set changed after the task was created.")
    if plan.plan_fingerprint != snapshot.expected_plan_fingerprint.lower():
        raise job_service.JobStateError("LabelMe import targets changed after preview. Run preview again.")
    if len(plan.operations) != snapshot.planned_samples:
        raise job_service.JobStateError("LabelMe import sample count changed after preview.")

    journal = _RollbackJournal(
        _journal_path(journal_job_id),
        journal_job_id=journal_job_id,
        dataset_id=dataset_id,
        source_sha256=snapshot.expected_source_sha256.lower(),
        request_fingerprint=snapshot.request_fingerprint,
    )
    journal.initialize()
    imported_samples = 0
    batches_committed = 0

    def result() -> dict[str, object]:
        return {
            "source_job_id": journal_job_id,
            "source_sha256": snapshot.expected_source_sha256.lower(),
            "planned_samples": snapshot.planned_samples,
            "planned_annotations": snapshot.planned_annotations,
            "imported_samples": imported_samples,
            "unique_samples_changed": journal.entry_count,
            "batches_committed": batches_committed,
            "preview_error_count": snapshot.preview_error_count,
            "rollback_available": journal.entry_count > 0,
        }

    try:
        for offset in range(0, len(plan.operations), IMPORT_BATCH_SIZE):
            context.checkpoint()
            batch = plan.operations[offset : offset + IMPORT_BATCH_SIZE]
            sample_ids = [item.sample_id for item in batch]
            with Session(context.engine) as session:
                samples = {
                    sample.id: sample
                    for sample in session.exec(
                        select(Sample)
                        .where(Sample.dataset_id == dataset_id, Sample.id.in_(sample_ids))
                        .options(selectinload(Sample.tags))
                    ).all()
                }
                if len(samples) != len(sample_ids):
                    raise job_service.JobStateError("A LabelMe import target disappeared after preview.")
                journal.append_missing(session, samples.values())
                for operation in batch:
                    original = journal.entries[operation.sample_id]
                    next_annotations = operation.annotations
                    if snapshot.strategy == "append":
                        next_annotations = annotation_import_service.append_annotations(
                            _entry_annotations_to_create(original),
                            operation.annotations,
                        )
                    annotation_service.replace_sample_annotations(
                        session,
                        operation.sample_id,
                        AnnotationReplaceRequest(annotations=next_annotations, save_mode="draft"),
                        commit=False,
                    )
                    if snapshot.sync_sample_tags:
                        annotation_service.sync_annotation_classes_to_sample_tags(
                            session,
                            operation.sample_id,
                            commit=False,
                        )
                session.commit()
            imported_samples += len(batch)
            batches_committed += 1
            context.report_progress(
                current=imported_samples,
                total=snapshot.planned_samples,
                stage="writing_annotations",
                error_count=snapshot.preview_error_count,
            )
        context.report_progress(
            current=imported_samples,
            total=snapshot.planned_samples,
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


def create_labelme_import_rollback_job(
    session: Session,
    source_job_id: int,
) -> LabelmeImportRollbackJobCreateResponse:
    source_job = job_service.get_job(session, source_job_id)
    if source_job.job_type != LABELME_IMPORT_JOB_TYPE:
        raise job_service.JobStateError("Only LabelMe import jobs can create LabelMe rollback jobs.")
    if source_job.status not in job_service.TERMINAL_STATUSES:
        raise job_service.JobStateError("LabelMe import rollback is available only after the import task stops.")
    if source_job.dataset_id is None:
        raise job_service.JobStateError("The LabelMe import job has no dataset.")
    journal_job_id = _root_retry_job_id(session, source_job)
    journal = _RollbackJournal.load(_journal_path(journal_job_id))
    if journal.dataset_id != source_job.dataset_id:
        raise job_service.JobStateError("LabelMe rollback journal dataset mismatch.")
    if journal.entry_count == 0:
        raise job_service.JobStateError("The LabelMe import task did not commit any recoverable changes.")

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
        job_type=LABELME_IMPORT_ROLLBACK_JOB_TYPE,
        dataset_id=source_job.dataset_id,
        parameter_match=("request_fingerprint", fingerprint),
    )
    if active is not None:
        session.commit()
        return LabelmeImportRollbackJobCreateResponse(job=active, created=False)
    dataset = dataset_service.get_dataset_or_404(session, source_job.dataset_id)
    created = job_service.create_job(
        session,
        JobCreate(
            job_type=LABELME_IMPORT_ROLLBACK_JOB_TYPE,
            title=f"回滚 LabelMe 导入：{dataset.name}",
            dataset_id=source_job.dataset_id,
            parameters=parameters,
            progress_total=journal.entry_count,
        ),
    )
    return LabelmeImportRollbackJobCreateResponse(job=created, created=True)


def run_labelme_import_rollback_job(context: JobContext, parameters: dict[str, object]) -> dict[str, object]:
    journal_job_id = _positive_int(parameters.get("journal_job_id"), "journal_job_id")
    expected_count = _positive_int(parameters.get("entry_count"), "entry_count")
    journal = _RollbackJournal.load(_journal_path(journal_job_id))
    if journal.entry_count != expected_count:
        raise job_service.JobStateError("LabelMe rollback journal changed after the task was created.")
    with Session(context.engine) as session:
        job = job_service.get_job(session, context.job_id)
        if job.dataset_id != journal.dataset_id:
            raise job_service.JobStateError("LabelMe rollback dataset mismatch.")

    restored = 0
    missing = 0
    batches_committed = 0

    def result() -> dict[str, object]:
        return {"source_job_id": journal_job_id, "restored": restored, "missing": missing, "batches_committed": batches_committed}

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
                        .where(Sample.dataset_id == journal.dataset_id, Sample.id.in_(sample_ids))
                        .options(selectinload(Sample.tags))
                    ).all()
                }
                for entry in batch:
                    sample = samples.get(int(entry["sample_id"]))
                    if sample is None:
                        missing += 1
                        continue
                    _restore_sample(session, journal.dataset_id, sample, entry)
                    restored += 1
                session.commit()
            batches_committed += 1
            context.report_progress(
                current=min(offset + len(batch), len(entries)),
                total=len(entries),
                stage="rolling_back_annotations",
                error_count=missing,
            )
        context.report_progress(current=len(entries), total=len(entries), stage="finalizing", error_count=missing)
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
                raise job_service.JobStateError("LabelMe rollback journal does not match this task.")
            self.entries = loaded.entries
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _append_json_lines(
            self.path,
            [{
                "kind": "header",
                "version": JOURNAL_VERSION,
                "journal_job_id": self.journal_job_id,
                "dataset_id": self.dataset_id,
                "source_sha256": self.source_sha256,
                "request_fingerprint": self.request_fingerprint,
            }],
            exclusive=True,
        )

    def append_missing(self, session: Session, samples) -> None:
        next_entries: list[dict[str, object]] = []
        for sample in samples:
            if sample.id is None or sample.id in self.entries:
                continue
            annotations = session.exec(
                select(Annotation).where(Annotation.sample_id == sample.id).order_by(Annotation.z_order, Annotation.id)
            ).all()
            next_entries.append({
                "kind": "sample",
                "sample_id": sample.id,
                "annotation_progress": sample.annotation_progress,
                "review_status": sample.review_status,
                "updated_at": sample.updated_at.isoformat(),
                "tag_names": sorted(tag.name for tag in sample.tags),
                "annotations": [_annotation_snapshot(item) for item in annotations],
            })
        if not next_entries:
            return
        _append_json_lines(self.path, next_entries)
        for entry in next_entries:
            self.entries[int(entry["sample_id"])] = entry

    @classmethod
    def load(cls, path: Path) -> _RollbackJournal:
        records = _read_json_lines(path)
        if not records or records[0].get("kind") != "header":
            raise job_service.JobStateError("LabelMe rollback journal is invalid.")
        header = records[0]
        if header.get("version") != JOURNAL_VERSION:
            raise job_service.JobStateError("LabelMe rollback journal version is unsupported.")
        journal = cls(
            path,
            journal_job_id=int(header["journal_job_id"]),
            dataset_id=int(header["dataset_id"]),
            source_sha256=str(header["source_sha256"]),
            request_fingerprint=str(header["request_fingerprint"]),
        )
        for record in records[1:]:
            if record.get("kind") != "sample":
                raise job_service.JobStateError("LabelMe rollback journal contains an invalid record.")
            journal.entries[int(record["sample_id"])] = record
        return journal


def _annotation_snapshot(annotation: Annotation) -> dict[str, object]:
    return {
        "class_id": annotation.class_id,
        "tag_id": annotation.tag_id,
        "label": annotation.label,
        "shape_type": annotation.shape_type,
        "points_json": annotation.points_json,
        "flags_json": annotation.flags_json,
        "attributes_json": annotation.attributes_json,
        "group_id": annotation.group_id,
        "z_order": annotation.z_order,
        "locked": annotation.locked,
        "hidden": annotation.hidden,
        "source": annotation.source,
        "notes": annotation.notes,
        "created_at": annotation.created_at.isoformat(),
        "updated_at": annotation.updated_at.isoformat(),
    }


def _entry_annotations_to_create(entry: dict[str, object]) -> list[AnnotationCreate]:
    annotations = entry.get("annotations")
    if not isinstance(annotations, list):
        raise job_service.JobStateError("LabelMe rollback journal annotation snapshot is invalid.")
    return [
        AnnotationCreate(
            class_id=item.get("class_id"),
            label=str(item["label"]),
            shape_type=str(item["shape_type"]),
            points=json.loads(str(item["points_json"])),
            flags=json.loads(str(item.get("flags_json") or "{}")),
            attributes=json.loads(str(item.get("attributes_json") or "{}")),
            group_id=item.get("group_id"),
            z_order=int(item.get("z_order", 0)),
            locked=bool(item.get("locked", False)),
            hidden=bool(item.get("hidden", False)),
            source=str(item.get("source") or "manual"),
            notes=item.get("notes"),
        )
        for item in annotations
        if isinstance(item, dict)
    ]


def _restore_sample(session: Session, dataset_id: int, sample: Sample, entry: dict[str, object]) -> None:
    for annotation in session.exec(select(Annotation).where(Annotation.sample_id == sample.id)).all():
        session.delete(annotation)
    annotations = entry.get("annotations")
    if not isinstance(annotations, list):
        raise job_service.JobStateError("LabelMe rollback journal annotation snapshot is invalid.")
    for item in annotations:
        if not isinstance(item, dict):
            raise job_service.JobStateError("LabelMe rollback journal annotation entry is invalid.")
        session.add(Annotation(
            sample_id=sample.id or 0,
            dataset_id=dataset_id,
            class_id=item.get("class_id"),
            tag_id=item.get("tag_id"),
            label=str(item["label"]),
            shape_type=str(item["shape_type"]),
            points_json=str(item["points_json"]),
            flags_json=item.get("flags_json"),
            attributes_json=item.get("attributes_json"),
            group_id=item.get("group_id"),
            z_order=int(item.get("z_order", 0)),
            locked=bool(item.get("locked", False)),
            hidden=bool(item.get("hidden", False)),
            source=str(item.get("source") or "manual"),
            notes=item.get("notes"),
            created_at=datetime.fromisoformat(str(item["created_at"])),
            updated_at=datetime.fromisoformat(str(item["updated_at"])),
        ))
    sample.annotation_progress = str(entry["annotation_progress"])
    sample.review_status = str(entry["review_status"])
    sample.updated_at = datetime.fromisoformat(str(entry["updated_at"]))
    tag_names = entry.get("tag_names")
    if not isinstance(tag_names, list):
        raise job_service.JobStateError("LabelMe rollback journal tag snapshot is invalid.")
    sample.tags = [_get_or_create_tag(session, dataset_id, str(name)) for name in tag_names]
    session.add(sample)


def _root_retry_job_id(session: Session, job: JobRead) -> int:
    current = job
    visited = {current.id}
    while current.retry_of_id is not None:
        if current.retry_of_id in visited:
            raise job_service.JobStateError("Job retry lineage contains a cycle.")
        visited.add(current.retry_of_id)
        current = job_service.get_job(session, current.retry_of_id)
        if current.job_type != LABELME_IMPORT_JOB_TYPE:
            raise job_service.JobStateError("LabelMe import retry lineage is invalid.")
    return current.id


def _journal_path(job_id: int) -> Path:
    root = (get_settings().storage_root / "job-recovery").resolve()
    job_directory = (root / f"job-{job_id}").resolve()
    if job_directory.parent != root:
        raise ValueError("LabelMe recovery path escaped its storage root.")
    return job_directory / JOURNAL_FILENAME


def _append_json_lines(path: Path, records: list[dict[str, object]], *, exclusive: bool = False) -> None:
    try:
        with path.open("x" if exclusive else "a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise job_service.JobStateError(f"Unable to persist LabelMe rollback journal: {exc}") from exc


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise job_service.JobStateError("LabelMe rollback journal is not available.") from exc
    records: list[dict[str, object]] = []
    for index, line in enumerate(raw_lines):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            if index == len(raw_lines) - 1:
                break
            raise job_service.JobStateError("LabelMe rollback journal is corrupted.") from exc
        if not isinstance(parsed, dict):
            raise job_service.JobStateError("LabelMe rollback journal contains a non-object record.")
        records.append(parsed)
    return records


def _positive_int(value: object, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise job_service.JobStateError(f"{field_name} must be a positive integer.") from exc
    if parsed <= 0:
        raise job_service.JobStateError(f"{field_name} must be a positive integer.")
    return parsed
