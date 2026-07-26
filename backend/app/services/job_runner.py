from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlmodel import Session, select

from app.models.job import Job
from app.schemas.job import JobRead, JobStatus
from app.services import job_service


JobHandler = Callable[["JobContext", dict[str, object]], dict[str, object] | None]
logger = logging.getLogger(__name__)


class JobCancelled(RuntimeError):
    """Raised by a cooperative checkpoint after cancellation was requested."""

    def __init__(
        self,
        message: str,
        *,
        result: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.result = result


class JobInterrupted(RuntimeError):
    """Raised by a cooperative checkpoint while the runner is stopping."""

    def __init__(
        self,
        message: str,
        *,
        result: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class JobContext:
    job_id: int
    engine: Engine
    stop_event: threading.Event

    def checkpoint(self) -> None:
        if self.stop_event.is_set():
            raise JobInterrupted("The job runner is stopping.")
        with Session(self.engine) as session:
            job = job_service.get_job(session, self.job_id)
        if job.cancel_requested_at is not None:
            raise JobCancelled("Cancellation was requested.")

    def report_progress(
        self,
        *,
        current: int,
        total: int | None = None,
        stage: str | None = None,
        error_count: int | None = None,
    ) -> JobRead:
        self.checkpoint()
        with Session(self.engine) as session:
            return job_service.update_job_progress(
                session,
                self.job_id,
                current=current,
                total=total,
                stage=stage,
                error_count=error_count,
            )


class JobRunner:
    """A single local worker with short, isolated SQLite write sessions."""

    def __init__(self, engine: Engine, *, poll_interval_seconds: float = 0.25):
        self.engine = engine
        self.poll_interval_seconds = poll_interval_seconds
        self._handlers: dict[str, JobHandler] = {}
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        if not job_type.strip():
            raise ValueError("job_type cannot be empty.")
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Handlers must be registered before the runner starts.")
        self._handlers[job_type] = handler

    def start(self) -> bool:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            with Session(self.engine) as session:
                try:
                    job_service.interrupt_running_jobs(session)
                except job_service.JobSchemaUnavailableError:
                    return False
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="dataset-manager-job-runner",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, *, timeout_seconds: float = 5.0) -> bool:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return True
            self._stop_event.set()
            self._wake_event.set()
        thread.join(timeout=timeout_seconds)
        stopped = not thread.is_alive()
        if stopped:
            with self._lifecycle_lock:
                if self._thread is thread:
                    self._thread = None
        return stopped

    def notify(self) -> None:
        self._wake_event.set()

    def run_once(self) -> bool:
        job = self._claim_next_job()
        if job is None:
            return False
        self._execute(job)
        return True

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("The local job runner could not process its next job.")
                processed = False
            if not processed:
                self._wake_event.wait(self.poll_interval_seconds)
                self._wake_event.clear()

    def _claim_next_job(self) -> JobRead | None:
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            job = session.exec(
                select(Job)
                .where(Job.status == "queued")
                .order_by(Job.created_at.asc(), Job.id.asc())
                .limit(1)
            ).first()
            if job is None:
                session.commit()
                return None
            if job.id is None:
                session.rollback()
                raise job_service.JobStateError("A persisted job must have an id.")
            return job_service.transition_job(
                session,
                job.id,
                "running",
                stage="starting",
            )

    def _execute(self, job: JobRead) -> None:
        context = JobContext(
            job_id=job.id,
            engine=self.engine,
            stop_event=self._stop_event,
        )
        handler = self._handlers.get(job.job_type)
        if handler is None:
            self._finish_failed(
                job.id,
                code="handler_not_registered",
                message=f"No handler is registered for job type {job.job_type}.",
            )
            return

        try:
            context.checkpoint()
            result = handler(context, job.parameters)
            if result is not None and not isinstance(result, dict):
                raise TypeError("A job handler result must be a JSON object or None.")
        except JobCancelled as exc:
            self._finish_terminal(
                job.id,
                "cancelled",
                stage="cancelled",
                result=exc.result,
                error={"code": "cancel_requested", "message": str(exc)},
            )
        except JobInterrupted as exc:
            self._finish_terminal(
                job.id,
                "interrupted",
                stage="process_stopped",
                result=exc.result,
                error={"code": "runner_stopped", "message": str(exc)},
            )
        except Exception as exc:  # A task failure must not terminate the worker.
            self._finish_failed(
                job.id,
                code="handler_failed",
                message=str(exc)[:2000],
                error_type=type(exc).__name__,
            )
        else:
            try:
                self._finish_terminal(
                    job.id,
                    "succeeded",
                    stage="completed",
                    result=result or {},
                )
            except (job_service.JobStateError, TypeError, ValueError) as exc:
                self._finish_failed(
                    job.id,
                    code="result_rejected",
                    message=str(exc)[:2000],
                    error_type=type(exc).__name__,
                )

    def _finish_terminal(
        self,
        job_id: int,
        status: JobStatus,
        *,
        stage: str,
        result: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> None:
        with Session(self.engine) as session:
            job_service.transition_job(
                session,
                job_id,
                status,
                stage=stage,
                result=result,
                error=error,
            )

    def _finish_failed(
        self,
        job_id: int,
        *,
        code: str,
        message: str,
        error_type: str | None = None,
    ) -> None:
        error: dict[str, object] = {"code": code, "message": message}
        if error_type is not None:
            error["type"] = error_type
        self._finish_terminal(job_id, "failed", stage="failed", error=error)
