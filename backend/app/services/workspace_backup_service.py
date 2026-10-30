"""Verified metadata bundles; restores only into a new directory."""
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import text
from sqlmodel import Session

from app.core import migrations
from app.core.config import get_settings
from app.schemas.industrial import AnomalyExportResponse
from app.schemas.job import JobCreate
from app.services import database_backup_service, industrial_plan_service, job_artifact_service, job_service
from app.services.job_runner import JobContext

JOB_TYPE = "workspace.metadata_backup"
METADATA_FOLDERS = ("industrial-plans", "job-recovery", "triage-directory-mapping-plans", "directory-export-plans")
MAX_BUNDLE_BYTES = 2 * 1024**3


def create_job(session: Session) -> AnomalyExportResponse:
    job_service.ensure_jobs_schema(session)
    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(session, job_type=JOB_TYPE, dataset_id=None)
    if active:
        session.commit()
        return AnomalyExportResponse(job=active, created=False)
    return AnomalyExportResponse(job=job_service.create_job(session, JobCreate(
        job_type=JOB_TYPE, title="备份元数据与快照", parameters={"bundle_version": 1})), created=True)


def _sha(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _safe_path(root: Path, name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or not pure.parts or any(p in {"..", "."} or ":" in p or "\\" in p for p in pure.parts):
        raise ValueError("Invalid metadata bundle path.")
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Metadata bundle path escaped its root.")
    return path


def _verify_snapshot_documents(database: Path, storage: Path) -> list[tuple[str, Path]]:
    files = []
    if not (storage / "snapshots").resolve().is_relative_to(storage.resolve()):
        raise ValueError("Snapshot storage escaped the application directory.")
    with closing(database_backup_service._open_read_only(database)) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "dataset_snapshots" not in tables:
            return []
        for sid, did, relative, expected in connection.execute("SELECT id, dataset_id, artifact_path, content_sha256 FROM dataset_snapshots"):
            path = _safe_path(storage / "snapshots", relative)
            if path.stat().st_size > 200_000_000:
                raise ValueError("Snapshot artifact is too large.")
            document = json.loads(path.read_text(encoding="utf-8"))
            if document["snapshot_id"] != sid or document["dataset_id"] != did or document["content_sha256"] != expected or industrial_plan_service.digest(document["content"]) != expected:
                raise ValueError("Snapshot artifact does not match its database record.")
            files.append((f"storage/snapshots/{relative}", path))
    return files


def _source_signature(database: Path, backup_job_id: int) -> tuple:
    with closing(database_backup_service._open_read_only(database)) as connection:
        jobs = tuple(connection.execute("SELECT id, status, updated_at FROM jobs WHERE id != ? ORDER BY id", (backup_job_id,)))
        if any(row[1] in {"queued", "running"} for row in jobs):
            raise ValueError("请等待其他后台任务结束后再备份元数据与快照。")
        revisions = tuple(connection.execute("SELECT id, revision FROM datasets ORDER BY id"))
    return revisions, jobs


def run_backup(context: JobContext, parameters: dict[str, object]) -> dict[str, object]:
    settings = get_settings()
    storage = settings.storage_root.resolve()
    artifacts = job_artifact_service.job_artifact_root()
    artifacts.mkdir(parents=True, exist_ok=True)
    signature = _source_signature(settings.database_path, context.job_id)
    with TemporaryDirectory(prefix=".workspace-backup-", dir=artifacts) as scratch:
        database = Path(scratch) / "app.db"
        database_backup_service._copy_database(settings.database_path, database, context=context)
        verification = database_backup_service._inspect_backup(database)
        if verification["foreign_key_violation_count"]:
            raise ValueError("数据库存在失效关联，请先完成完整性维护。")
        files = [("database/app.db", database), *_verify_snapshot_documents(database, storage)]
        for folder in METADATA_FOLDERS:
            source_root = storage / folder
            if not source_root.resolve().is_relative_to(storage):
                raise ValueError("Metadata folder escaped application storage.")
            if source_root.exists():
                for path in source_root.rglob("*"):
                    if path.is_file() and path.suffix != ".tmp":
                        resolved = path.resolve()
                        if not resolved.is_relative_to(source_root.resolve()):
                            raise ValueError("Metadata symlink escaped storage.")
                        files.append((f"storage/{folder}/{path.relative_to(source_root).as_posix()}", path))
        if len(files) > 20000 or sum(path.stat().st_size for _, path in files) > MAX_BUNDLE_BYTES:
            raise ValueError("元数据包超过试用版上限（20000 文件 / 2 GiB），请先归档旧任务。")
        manifest_files = []
        filename = f"metadata-workspace-{context.job_id}.zip"
        with job_artifact_service.JobArtifactWorkspace(artifacts, job_id=context.job_id,
            filename=filename, media_type="application/zip") as workspace:
            with ZipFile(workspace.path, "w", ZIP_DEFLATED, allowZip64=True) as archive:
                for index, (name, path) in enumerate(files, 1):
                    context.checkpoint()
                    digest = hashlib.sha256()
                    size = 0
                    with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                        while chunk := source.read(1024**2):
                            context.checkpoint()
                            target.write(chunk); digest.update(chunk); size += len(chunk)
                    manifest_files.append(dict(path=name, sha256=digest.hexdigest(), size_bytes=size))
                    context.report_progress(current=index, total=len(files), stage="copying_files")
                manifest = dict(bundle_version=1, verification=verification, raw_files_included=False,
                    downloadable_job_artifacts_included=False, files=manifest_files,
                    scope="SQLite + referenced snapshots + frozen plans + task recovery metadata")
                archive.writestr("bundle-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            with ZipFile(workspace.path) as archive:
                for item in manifest_files:
                    context.checkpoint()
                    with archive.open(item["path"]) as file:
                        if hashlib.file_digest(file, "sha256").hexdigest() != item["sha256"]:
                            raise ValueError("Metadata bundle verification failed.")
            if _source_signature(settings.database_path, context.job_id) != signature:
                raise ValueError("备份期间元数据或任务发生变化，请重新创建备份。")
            artifact = workspace.finalize(checkpoint=context.checkpoint)
        return dict(verification=verification, file_count=len(files), raw_files_included=False,
            artifact=dict(filename=artifact.filename, media_type=artifact.media_type,
                          size_bytes=artifact.size_bytes, sha256=artifact.sha256))


def restore_bundle(archive_path: Path, target_directory: Path) -> dict:
    """Validate in staging, then publish a new folder; never replace a live DB."""
    target = target_directory.resolve()
    if target.exists() or not target.parent.is_dir():
        raise ValueError("恢复目标必须是父目录已存在的新目录；不会替换当前工作区。")
    temporary = target.parent / f".{target.name}.restore-{uuid4().hex}.part"
    temporary.mkdir()
    try:
        with ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or len(names) > 20001:
                raise ValueError("Duplicate or oversized bundle inventory.")
            if archive.getinfo("bundle-manifest.json").file_size > 10_000_000:
                raise ValueError("Manifest is too large.")
            manifest = json.loads(archive.read("bundle-manifest.json"))
            if manifest["bundle_version"] != 1:
                raise ValueError("Unsupported metadata bundle version.")
            items = manifest["files"]
            expected = {i["path"] for i in items}
            if len(expected) != len(items) or set(names) != expected | {"bundle-manifest.json"} or "database/app.db" not in expected:
                raise ValueError("Bundle inventory does not match the manifest.")
            if sum(archive.getinfo(i["path"]).file_size for i in items) > MAX_BUNDLE_BYTES:
                raise ValueError("Bundle exceeds the restoration size limit.")
            for item in items:
                name = item["path"]
                if name != "database/app.db" and not name.startswith(tuple(f"storage/{folder}/" for folder in ("snapshots", *METADATA_FOLDERS))):
                    raise ValueError("Unrecognized file in metadata bundle.")
                destination = _safe_path(temporary, name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as source, destination.open("xb") as output:
                    while chunk := source.read(1024**2):
                        size += len(chunk)
                        if size > item["size_bytes"] or size > MAX_BUNDLE_BYTES:
                            raise ValueError("Uncompressed size exceeds manifest.")
                        output.write(chunk); digest.update(chunk)
                if size != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
                    raise ValueError("Bundle file checksum mismatch.")
        database = temporary / "database/app.db"
        verification = database_backup_service._inspect_backup(database)
        if verification["foreign_key_violation_count"] or verification != manifest["verification"] or verification["current_revision"] != migrations.head_revision():
            raise ValueError("数据库结构或计数与备份不一致；请用匹配版本恢复。")
        _verify_snapshot_documents(database, temporary / "storage")
        (temporary / "restore-report.json").write_text(json.dumps(dict(verification=verification,
            raw_files_included=False, restored_files=len(items), current_workspace_replaced=False), ensure_ascii=False, indent=2), encoding="utf-8")
        os.rename(temporary, target)
        return dict(target_directory=str(target), database_path=str(target / "database/app.db"),
                    storage_root=str(target / "storage"), verification=verification,
                    current_workspace_replaced=False, raw_files_included=False)
    finally:
        # Only the uniquely created sibling staging folder is ever removed.
        if temporary.parent == target.parent and temporary.name.startswith(f".{target.name}.restore-") and temporary.exists():
            shutil.rmtree(temporary)
