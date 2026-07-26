from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
from types import TracebackType
from uuid import uuid4


HASH_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class JobArtifactMetadata:
    path: Path
    filename: str
    media_type: str
    size_bytes: int
    sha256: str


class JobArtifactWorkspace:
    """Publish one job artifact atomically and clean incomplete output."""

    def __init__(
        self,
        root: Path,
        *,
        job_id: int,
        filename: str,
        media_type: str,
    ) -> None:
        if job_id <= 0:
            raise ValueError("job_id must be positive.")
        _validate_filename(filename)
        if not media_type.strip():
            raise ValueError("media_type cannot be empty.")

        self.root = root.resolve()
        self.job_id = job_id
        self.filename = filename
        self.media_type = media_type
        self.job_directory = _resolve_job_directory(self.root, job_id)
        self.final_path = self.job_directory / filename
        self._temporary_path: Path | None = None
        self._active = False
        self._published = False
        self._finalized = False

    @property
    def path(self) -> Path:
        if not self._active or self._temporary_path is None:
            raise RuntimeError("The artifact workspace is not active.")
        return self._temporary_path

    def __enter__(self) -> JobArtifactWorkspace:
        if self._active:
            raise RuntimeError("The artifact workspace is already active.")
        self.job_directory.mkdir(parents=True, exist_ok=True)
        if self.final_path.exists():
            raise FileExistsError(f"Job artifact already exists: {self.filename}")
        self._temporary_path = (
            self.job_directory / f".{self.filename}.{uuid4().hex}.part"
        )
        self._active = True
        return self

    def finalize(self) -> JobArtifactMetadata:
        temporary_path = self.path
        if self._finalized:
            raise RuntimeError("The artifact workspace is already finalized.")
        if not temporary_path.is_file():
            raise FileNotFoundError("The temporary artifact was not created.")
        if self.final_path.exists():
            raise FileExistsError(f"Job artifact already exists: {self.filename}")

        os.replace(temporary_path, self.final_path)
        self._published = True
        size_bytes = self.final_path.stat().st_size
        digest = _hash_file(self.final_path)
        self._finalized = True
        return JobArtifactMetadata(
            path=self.final_path,
            filename=self.filename,
            media_type=self.media_type,
            size_bytes=size_bytes,
            sha256=digest,
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        temporary_path = self._temporary_path
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if self._published and (exc_type is not None or not self._finalized):
            self.final_path.unlink(missing_ok=True)
        self._active = False
        self._remove_empty_job_directory()

    def _remove_empty_job_directory(self) -> None:
        try:
            self.job_directory.rmdir()
        except OSError:
            pass


def resolve_job_artifact(
    root: Path,
    *,
    job_id: int,
    filename: str,
) -> Path:
    if job_id <= 0:
        raise ValueError("job_id must be positive.")
    _validate_filename(filename)
    resolved_root = root.resolve()
    job_directory = _resolve_job_directory(resolved_root, job_id)
    path = (job_directory / filename).resolve()
    if path.parent != job_directory:
        raise ValueError("Artifact path escaped its job directory.")
    return path


def _resolve_job_directory(root: Path, job_id: int) -> Path:
    job_directory = (root / f"job-{job_id}").resolve()
    if job_directory.parent != root:
        raise ValueError("Artifact job directory escaped its storage root.")
    return job_directory


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or filename in {".", ".."}
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or ":" in filename
    ):
        raise ValueError("Artifact filename must be a plain filename.")


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
