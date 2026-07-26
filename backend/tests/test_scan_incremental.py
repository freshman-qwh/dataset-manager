from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine
import pytest

from app.models.dataset import Dataset
from app.schemas.scan import ScanRequest
from app.services import scan_service


def _engine(database_path: Path):
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _dataset(session: Session, root: Path) -> Dataset:
    dataset = Dataset(name="Incremental scan", root_path=str(root))
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset


def test_incremental_scan_skips_hash_for_unchanged_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    files = [root / f"sample-{index}.jpg" for index in range(3)]
    for index, path in enumerate(files):
        path.write_bytes(f"image-{index}".encode())
    before = {path: path.read_bytes() for path in files}

    engine = _engine(tmp_path / "scan.db")
    real_hash = scan_service.sha256_file
    hash_calls: list[Path] = []

    def tracked_hash(path: Path) -> str:
        hash_calls.append(path)
        return real_hash(path)

    monkeypatch.setattr(scan_service, "sha256_file", tracked_hash)
    with Session(engine) as session:
        dataset = _dataset(session, root)
        assert dataset.id is not None
        first = scan_service.scan_dataset(
            session,
            dataset.id,
            ScanRequest(folder_path=str(root)),
            batch_size=2,
            hash_workers=2,
        )
        assert first.imported == 3
        assert first.hashed == 3
        assert first.batches_committed == 2

        hash_calls.clear()
        second = scan_service.scan_dataset(
            session,
            dataset.id,
            ScanRequest(folder_path=str(root)),
            batch_size=2,
            hash_workers=2,
        )
        assert second.unchanged == 3
        assert second.hashed == 0
        assert second.hash_skipped_unchanged == 3
        assert hash_calls == []

    assert {path: path.read_bytes() for path in files} == before
    engine.dispose()


def test_incremental_scan_rehashes_changes_and_marks_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    changed_path = root / "changed.jpg"
    missing_path = root / "missing.jpg"
    changed_path.write_bytes(b"before")
    missing_path.write_bytes(b"missing")

    engine = _engine(tmp_path / "changes.db")
    real_hash = scan_service.sha256_file
    hash_calls: list[Path] = []

    def tracked_hash(path: Path) -> str:
        hash_calls.append(path)
        return real_hash(path)

    monkeypatch.setattr(scan_service, "sha256_file", tracked_hash)
    with Session(engine) as session:
        dataset = _dataset(session, root)
        assert dataset.id is not None
        scan_service.scan_dataset(session, dataset.id, ScanRequest(folder_path=str(root)))

        previous = changed_path.stat()
        changed_path.write_bytes(b"after!")
        os.utime(
            changed_path,
            ns=(previous.st_atime_ns, previous.st_mtime_ns + 2_000_000_000),
        )
        missing_path.unlink()
        hash_calls.clear()

        result = scan_service.scan_dataset(
            session,
            dataset.id,
            ScanRequest(folder_path=str(root)),
        )
        assert result.updated == 1
        assert result.missing == 1
        assert result.hashed == 1
        assert hash_calls == [changed_path]
    engine.dispose()


def test_scan_hash_parallelism_is_limited(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    for index in range(6):
        (root / f"parallel-{index}.jpg").write_bytes(str(index).encode())

    engine = _engine(tmp_path / "parallel.db")
    real_hash = scan_service.sha256_file
    lock = threading.Lock()
    active = 0
    peak = 0

    def observed_hash(path: Path) -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        try:
            return real_hash(path)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(scan_service, "sha256_file", observed_hash)
    with Session(engine) as session:
        dataset = _dataset(session, root)
        assert dataset.id is not None
        result = scan_service.scan_dataset(
            session,
            dataset.id,
            ScanRequest(folder_path=str(root)),
            batch_size=6,
            hash_workers=2,
        )
        assert result.imported == 6
        assert peak == 2
    engine.dispose()


def test_scan_stop_reports_safely_committed_partial_batches(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    for index in range(5):
        (root / f"partial-{index}.jpg").write_bytes(str(index).encode())

    engine = _engine(tmp_path / "partial.db")
    checkpoint_calls = 0

    class StopRequested(RuntimeError):
        pass

    def checkpoint() -> None:
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        if checkpoint_calls >= 6:
            raise StopRequested

    with Session(engine) as session:
        dataset = _dataset(session, root)
        assert dataset.id is not None
        with pytest.raises(scan_service.ScanStopped) as stopped:
            scan_service.scan_dataset(
                session,
                dataset.id,
                ScanRequest(folder_path=str(root)),
                batch_size=2,
                checkpoint=checkpoint,
            )
        assert isinstance(stopped.value.__cause__, StopRequested)
        assert stopped.value.result.imported == 2
        assert stopped.value.result.batches_committed == 1

        resumed = scan_service.scan_dataset(
            session,
            dataset.id,
            ScanRequest(folder_path=str(root)),
            batch_size=2,
        )
        assert resumed.imported == 3
        assert resumed.unchanged == 2
    engine.dispose()
