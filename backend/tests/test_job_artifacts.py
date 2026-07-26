from hashlib import sha256
from pathlib import Path

import pytest

from app.services.job_artifact_service import (
    JobArtifactWorkspace,
    resolve_job_artifact,
)


def test_job_artifact_workspace_publishes_atomically_with_metadata(
    tmp_path: Path,
) -> None:
    payload = b"bounded artifact payload"

    with JobArtifactWorkspace(
        tmp_path,
        job_id=7,
        filename="annotations.zip",
        media_type="application/zip",
    ) as workspace:
        assert workspace.path.suffix == ".part"
        workspace.path.write_bytes(payload)
        metadata = workspace.finalize()

    assert metadata.path == tmp_path / "job-7" / "annotations.zip"
    assert metadata.path.read_bytes() == payload
    assert metadata.size_bytes == len(payload)
    assert metadata.sha256 == sha256(payload).hexdigest()
    assert not list((tmp_path / "job-7").glob("*.part"))


def test_job_artifact_workspace_cleans_incomplete_output_on_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="generation failed"):
        with JobArtifactWorkspace(
            tmp_path,
            job_id=8,
            filename="annotations.json",
            media_type="application/json",
        ) as workspace:
            workspace.path.write_text("partial", encoding="utf-8")
            raise RuntimeError("generation failed")

    assert not (tmp_path / "job-8").exists()


def test_job_artifact_workspace_removes_published_output_when_exit_fails(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="result persistence failed"):
        with JobArtifactWorkspace(
            tmp_path,
            job_id=9,
            filename="annotations.zip",
            media_type="application/zip",
        ) as workspace:
            workspace.path.write_bytes(b"complete")
            workspace.finalize()
            raise RuntimeError("result persistence failed")

    assert not (tmp_path / "job-9").exists()


def test_job_artifact_workspace_requires_explicit_finalize(tmp_path: Path) -> None:
    with JobArtifactWorkspace(
        tmp_path,
        job_id=10,
        filename="annotations.zip",
        media_type="application/zip",
    ) as workspace:
        workspace.path.write_bytes(b"not published")

    assert not (tmp_path / "job-10").exists()


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "../escape.zip", "nested/file.zip", r"nested\\file.zip", "C:escape.zip"],
)
def test_job_artifact_paths_reject_unsafe_filenames(
    tmp_path: Path,
    filename: str,
) -> None:
    with pytest.raises(ValueError, match="plain filename"):
        JobArtifactWorkspace(
            tmp_path,
            job_id=11,
            filename=filename,
            media_type="application/zip",
        )
    with pytest.raises(ValueError, match="plain filename"):
        resolve_job_artifact(tmp_path, job_id=11, filename=filename)


def test_resolve_job_artifact_returns_deterministic_job_path(
    tmp_path: Path,
) -> None:
    assert resolve_job_artifact(
        tmp_path,
        job_id=12,
        filename="result.json",
    ) == (tmp_path / "job-12" / "result.json").resolve()
