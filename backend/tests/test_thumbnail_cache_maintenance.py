from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session

from app.api import system
from app.core import migrations
from app.core.database import create_legacy_baseline_tables, get_session
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.services import (
    job_service,
    thumbnail_cache_service,
    thumbnail_maintenance_service,
    thumbnail_service,
)
from app.services.job_runner import JobRunner


def _migrated_engine(database_path: Path):
    migrations.upgrade_database(database_path)
    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def _add_live_hashes(session: Session, hashes: list[str]) -> None:
    dataset = Dataset(name="cache maintenance")
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    assert dataset.id is not None
    for index, file_hash in enumerate(hashes):
        session.add(
            Sample(
                dataset_id=dataset.id,
                filename=f"sample-{index}.png",
                absolute_path=f"C:/raw/sample-{index}.png",
                relative_path=f"sample-{index}.png",
                file_size=1,
                extension=".png",
                file_type="image",
                mime_type="image/png",
                file_hash=file_hash,
                file_status="normal",
            )
        )
    session.commit()


def _write_cache_file(root: Path, file_hash: str, size: int, mtime: float) -> Path:
    path = thumbnail_service.thumbnail_path(file_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    assert path.is_relative_to(root)
    return path


def test_thumbnail_cache_maintenance_removes_only_owned_obsolete_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "thumbnails"
    monkeypatch.setattr(thumbnail_service, "thumbnail_cache_root", lambda: root)
    monkeypatch.setattr(thumbnail_cache_service, "thumbnail_cache_root", lambda: root)
    engine = _migrated_engine(tmp_path / "cache.db")
    now = time.time()
    live_hash = "a" * 64
    orphan_hash = "b" * 64
    progress_updates: list[tuple[int, int]] = []
    prune_updates: list[tuple[int, int]] = []
    with Session(engine) as session:
        _add_live_hashes(session, [live_hash])
        live = _write_cache_file(root, live_hash, 40, now - 10)
        orphan = _write_cache_file(root, orphan_hash, 30, now - 20)
        obsolete = root / "v0" / "cc" / f"{'c' * 64}.webp"
        obsolete.parent.mkdir(parents=True)
        obsolete.write_bytes(b"old")
        stale_part = root / "v1" / "aa" / "stale.part"
        stale_part.parent.mkdir(parents=True, exist_ok=True)
        stale_part.write_bytes(b"part")
        os.utime(stale_part, (now - 7200, now - 7200))
        recent_part = root / "v1" / "aa" / "recent.part"
        recent_part.write_bytes(b"part")
        unknown = root / "notes.txt"
        unknown.write_text("keep", encoding="utf-8")

        result = thumbnail_cache_service.maintain_thumbnail_cache(
            session,
            max_bytes=1024,
            now_timestamp=now,
            progress=lambda current, total: progress_updates.append((current, total)),
            prune_started=lambda current, total: prune_updates.append((current, total)),
        )

    assert result["old_spec_removed_count"] == 1
    assert result["orphan_removed_count"] == 1
    assert result["stale_part_removed_count"] == 1
    assert result["capacity_removed_count"] == 0
    assert result["error_count"] == 0
    assert live.exists()
    assert not orphan.exists()
    assert not obsolete.exists()
    assert not stale_part.exists()
    assert recent_part.exists()
    assert unknown.exists()
    assert progress_updates[-1][0] == progress_updates[-1][1]
    assert prune_updates == [progress_updates[-1]]
    engine.dispose()


def test_thumbnail_cache_maintenance_enforces_capacity_oldest_first(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "thumbnails"
    monkeypatch.setattr(thumbnail_service, "thumbnail_cache_root", lambda: root)
    monkeypatch.setattr(thumbnail_cache_service, "thumbnail_cache_root", lambda: root)
    engine = _migrated_engine(tmp_path / "capacity.db")
    now = time.time()
    hashes = ["1" * 64, "2" * 64, "3" * 64]
    with Session(engine) as session:
        _add_live_hashes(session, hashes)
        oldest = _write_cache_file(root, hashes[0], 60, now - 30)
        middle = _write_cache_file(root, hashes[1], 70, now - 20)
        newest = _write_cache_file(root, hashes[2], 80, now - 10)
        result = thumbnail_cache_service.maintain_thumbnail_cache(
            session,
            max_bytes=150,
            now_timestamp=now,
        )

    assert result["size_before_bytes"] == 210
    assert result["size_after_bytes"] == 150
    assert result["capacity_removed_count"] == 1
    assert result["capacity_removed_bytes"] == 60
    assert not oldest.exists()
    assert middle.exists()
    assert newest.exists()
    engine.dispose()


def test_thumbnail_maintenance_job_is_due_aware_and_old_db_returns_409(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "thumbnails"
    monkeypatch.setattr(thumbnail_service, "thumbnail_cache_root", lambda: root)
    monkeypatch.setattr(thumbnail_cache_service, "thumbnail_cache_root", lambda: root)
    monkeypatch.setattr(thumbnail_maintenance_service, "thumbnail_cache_root", lambda: root)
    engine = _migrated_engine(tmp_path / "maintenance-job.db")
    runner = JobRunner(engine, poll_interval_seconds=0.01)
    runner.register_handler(
        thumbnail_maintenance_service.THUMBNAIL_MAINTENANCE_JOB_TYPE,
        thumbnail_maintenance_service.run_thumbnail_maintenance_job,
    )
    with Session(engine) as session:
        created = thumbnail_maintenance_service.create_thumbnail_maintenance_job(
            session,
            force=False,
        )
        duplicate = thumbnail_maintenance_service.create_thumbnail_maintenance_job(
            session,
            force=False,
        )
        assert created.created is True
        assert created.job is not None
        assert duplicate.created is False
        assert duplicate.job is not None
        assert duplicate.job.id == created.job.id

    assert runner.run_once() is True
    with Session(engine) as session:
        completed = job_service.get_job(session, created.job.id)
        skipped = thumbnail_maintenance_service.create_thumbnail_maintenance_job(
            session,
            force=False,
        )
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["size_after_bytes"] == 0
    assert skipped.created is False
    assert skipped.job is None
    assert skipped.due is False
    engine.dispose()

    legacy_engine = create_engine(
        f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    create_legacy_baseline_tables(legacy_engine)
    app = FastAPI()
    app.include_router(system.router)

    def override_session():
        with Session(legacy_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        response = client.post("/api/system/thumbnail-cache/maintenance-jobs")
    assert response.status_code == 409
    legacy_engine.dispose()
