from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import threading
import time
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.api import datasets, directory_exports, jobs, samples, triage
from app.core.database import get_session
from app.services import (
    directory_export_job_service,
    directory_export_service,
    job_artifact_service,
    job_service,
)
from app.services.job_runner import JobRunner


def _make_app(engine) -> FastAPI:
    app = FastAPI()
    app.include_router(datasets.router)
    app.include_router(samples.router)
    app.include_router(triage.router)
    app.include_router(directory_exports.router)
    app.include_router(jobs.router)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


def _create_dataset(client: TestClient, raw_root: Path) -> tuple[int, list[dict]]:
    raw_root.mkdir()
    png = b"\x89PNG\r\n\x1a\n" + b"directory-export-test"
    for index, name in enumerate(("a.png", "b.png", "c.png", "d.png")):
        (raw_root / name).write_bytes(png + bytes([index]))
    created = client.post(
        "/api/datasets",
        json={"name": "Directory export", "root_path": str(raw_root)},
    )
    assert created.status_code == 201
    dataset_id = created.json()["id"]
    assert client.post(
        f"/api/datasets/{dataset_id}/scan",
        json={"folder_path": str(raw_root)},
    ).status_code == 200
    listed = client.get(
        f"/api/datasets/{dataset_id}/samples",
        params={"page_size": 20, "sort_by": "relative_path", "sort_order": "asc"},
    )
    assert listed.status_code == 200
    return dataset_id, listed.json()["items"]


def _triage_payload(sample: dict, **values) -> dict:
    return {
        "expected_version": sample["triage_version"],
        "expected_file_hash": sample["file_hash"],
        "triage_status": values.get("triage_status", "untriaged"),
        "ok_grade": values.get("ok_grade"),
        "defect_severity": values.get("defect_severity"),
        "defect_type_ids": values.get("defect_type_ids", []),
        "primary_defect_type_id": values.get("primary_defect_type_id"),
        "triage_note": values.get("triage_note"),
    }


def _prepare_triage(client: TestClient, dataset_id: int, samples: list[dict]) -> None:
    scratch = client.post(
        f"/api/datasets/{dataset_id}/defect-types",
        json={"name": "划痕", "code": "scratch"},
    ).json()
    assert client.put(
        f"/api/samples/{samples[0]['id']}/triage",
        json=_triage_payload(samples[0], triage_status="ok", ok_grade="clear"),
    ).status_code == 200
    assert client.put(
        f"/api/samples/{samples[1]['id']}/triage",
        json=_triage_payload(
            samples[1],
            triage_status="ng",
            defect_severity="severe",
            defect_type_ids=[scratch["id"]],
            primary_defect_type_id=scratch["id"],
        ),
    ).status_code == 200
    assert client.put(
        f"/api/samples/{samples[2]['id']}/triage",
        json=_triage_payload(samples[2], triage_status="pending"),
    ).status_code == 200


def _runner(engine) -> JobRunner:
    runner = JobRunner(engine)
    runner.register_handler(
        directory_export_job_service.DIRECTORY_EXPORT_JOB_TYPE,
        directory_export_job_service.run_directory_export_job,
    )
    return runner


def _wait_for_terminal(engine, job_id: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session(engine) as session:
            job = job_service.get_job(session, job_id)
        if job.status in job_service.TERMINAL_STATUSES:
            return job
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not reach a terminal state.")


def test_zip_directory_export_preview_freezes_plan_and_writes_verified_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'zip-export.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    plan_root = tmp_path / "plans"
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(directory_export_service, "directory_export_plan_root", lambda: plan_root)
    monkeypatch.setattr(job_artifact_service, "job_artifact_root", lambda: artifact_root)
    app = _make_app(engine)
    raw_root = tmp_path / "raw"

    with TestClient(app) as client:
        dataset_id, samples = _create_dataset(client, raw_root)
        _prepare_triage(client, dataset_id, samples)
        before = {path.name: path.read_bytes() for path in raw_root.iterdir()}

        preview = client.post(
            f"/api/datasets/{dataset_id}/directory-export-previews",
            json={
                "delivery": "zip",
                "sample_query": {"sort_by": "relative_path", "sort_order": "asc"},
            },
        )
        assert preview.status_code == 201
        plan = preview.json()
        assert plan["selected_count"] == 4
        assert plan["included_count"] == 2
        assert plan["excluded_count"] == 2
        assert plan["directory_counts"] == {"ng/scratch/severe": 1, "ok/clear": 1}
        assert plan["exclusion_counts"] == {
            "pending_excluded": 1,
            "untriaged_excluded": 1,
        }
        assert len(plan["plan_hash"]) == 64
        assert plan["output_name"].endswith(".zip")

        non_image_scope = client.post(
            f"/api/datasets/{dataset_id}/directory-export-previews",
            json={"delivery": "zip", "sample_query": {"file_type": "video"}},
        )
        assert non_image_scope.status_code == 201
        assert non_image_scope.json()["selected_count"] == 0
        assert non_image_scope.json()["blocked"] is True

        second_page = client.get(
            f"/api/datasets/{dataset_id}/directory-export-previews/{plan['plan_id']}",
            params={"page": 2, "page_size": 1},
        )
        assert second_page.status_code == 200
        assert second_page.json()["page_count"] == 4
        assert second_page.json()["items"][0]["source_relative_path"] == "b.png"

        created = client.post(
            f"/api/datasets/{dataset_id}/directory-export-jobs",
            json={"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]},
        )
        assert created.status_code == 201
        job_id = created.json()["job"]["id"]
        duplicate = client.post(
            f"/api/datasets/{dataset_id}/directory-export-jobs",
            json={"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["job"]["id"] == job_id

        assert _runner(engine).run_once() is True
        completed = client.get(f"/api/jobs/{job_id}").json()
        assert completed["status"] == "succeeded"
        assert completed["result"]["exported_sample_count"] == 2
        downloaded = client.get(f"/api/jobs/{job_id}/artifact")
        assert downloaded.status_code == 200
        assert sha256(downloaded.content).hexdigest() == completed["result"]["artifact"]["sha256"]
        with ZipFile(BytesIO(downloaded.content)) as archive:
            names = set(archive.namelist())
            assert f"ok/clear/{samples[0]['id']}__a.png" in names
            assert f"ng/scratch/severe/{samples[1]['id']}__b.png" in names
            assert {"manifest.jsonl", "export-config.json", "export-report.json"}.issubset(names)
            manifest = archive.read("manifest.jsonl").decode("utf-8")
            assert "source_absolute_path" not in manifest
            assert len([line for line in manifest.splitlines() if line]) == 2
            report = json.loads(archive.read("export-report.json"))
            assert report["exported_sample_count"] == 2
        assert {path.name: path.read_bytes() for path in raw_root.iterdir()} == before
        assert not list(raw_root.rglob("*.json"))
        assert not list(artifact_root.rglob("*.part"))

    engine.dispose()


def test_server_directory_export_includes_explicit_queues_and_publishes_atomically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'directory-export.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    plan_root = tmp_path / "plans"
    output_root = tmp_path / "managed-exports"
    monkeypatch.setattr(directory_export_service, "directory_export_plan_root", lambda: plan_root)
    monkeypatch.setattr(directory_export_service, "directory_export_output_root", lambda: output_root)
    app = _make_app(engine)
    raw_root = tmp_path / "raw"

    with TestClient(app) as client:
        dataset_id, samples = _create_dataset(client, raw_root)
        _prepare_triage(client, dataset_id, samples)
        policy = client.get(f"/api/datasets/{dataset_id}/triage-policy").json()
        configured = client.put(
            f"/api/datasets/{dataset_id}/triage-policy",
            json={**policy, "split_ok": False, "ng_grouping": "none"},
        )
        assert configured.status_code == 200
        preview = client.post(
            f"/api/datasets/{dataset_id}/directory-export-previews",
            json={
                "delivery": "directory",
                "include_pending": True,
                "include_untriaged": True,
                "include_outdated": True,
                "run_name": "客户 A / 首轮",
            },
        ).json()
        assert preview["included_count"] == 4
        assert preview["directory_counts"] == {
            "ng": 1,
            "ok": 1,
            "pending": 1,
            "untriaged": 1,
        }
        assert "/" not in preview["output_name"]

        created = client.post(
            f"/api/datasets/{dataset_id}/directory-export-jobs",
            json={"plan_id": preview["plan_id"], "plan_hash": preview["plan_hash"]},
        ).json()
        job_id = created["job"]["id"]
        assert _runner(engine).run_once() is True
        completed = client.get(f"/api/jobs/{job_id}").json()
        assert completed["status"] == "succeeded"
        result = completed["result"]
        final_path = Path(result["output_path"])
        assert final_path.parent == output_root.resolve()
        assert (final_path / f"ok/{samples[0]['id']}__a.png").is_file()
        assert (final_path / f"ng/{samples[1]['id']}__b.png").is_file()
        assert (final_path / f"pending/{samples[2]['id']}__c.png").is_file()
        assert (final_path / f"untriaged/{samples[3]['id']}__d.png").is_file()
        assert (final_path / "manifest.jsonl").is_file()
        assert (final_path / "export-config.json").is_file()
        assert (final_path / "export-report.json").is_file()
        assert (final_path / ".dataset-manager-export.json").is_file()
        assert not list(output_root.glob("*.part"))
        assert not list(output_root.glob(".*.part"))

        repeated = client.post(
            f"/api/datasets/{dataset_id}/directory-export-jobs",
            json={"plan_id": preview["plan_id"], "plan_hash": preview["plan_hash"]},
        )
        assert repeated.status_code == 201
        repeated_id = repeated.json()["job"]["id"]
        assert _runner(engine).run_once() is True
        recovered = client.get(f"/api/jobs/{repeated_id}").json()
        assert recovered["status"] == "succeeded"
        assert recovered["result"]["recovered_existing_output"] is True

    engine.dispose()


def test_export_rejects_stale_plan_and_cleans_changed_source_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'changed-export.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    plan_root = tmp_path / "plans"
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(directory_export_service, "directory_export_plan_root", lambda: plan_root)
    monkeypatch.setattr(job_artifact_service, "job_artifact_root", lambda: artifact_root)
    app = _make_app(engine)
    raw_root = tmp_path / "raw"

    with TestClient(app) as client:
        dataset_id, samples = _create_dataset(client, raw_root)
        _prepare_triage(client, dataset_id, samples)
        preview = client.post(
            f"/api/datasets/{dataset_id}/directory-export-previews",
            json={"delivery": "zip"},
        ).json()
        (raw_root / "a.png").write_bytes(b"changed after preview")
        created = client.post(
            f"/api/datasets/{dataset_id}/directory-export-jobs",
            json={"plan_id": preview["plan_id"], "plan_hash": preview["plan_hash"]},
        )
        assert created.status_code == 201
        job_id = created.json()["job"]["id"]
        assert _runner(engine).run_once() is True
        failed = client.get(f"/api/jobs/{job_id}").json()
        assert failed["status"] == "failed"
        assert "预检后发生变化" in failed["error"]["message"]
        assert not list(artifact_root.rglob("*.zip"))
        assert not list(artifact_root.rglob("*.part"))

        fresh = client.post(
            f"/api/datasets/{dataset_id}/directory-export-previews",
            json={"delivery": "zip", "include_outdated": True},
        ).json()
        policy = client.get(f"/api/datasets/{dataset_id}/triage-policy").json()
        changed_policy = client.put(
            f"/api/datasets/{dataset_id}/triage-policy",
            json={**policy, "instructions": "changed after preview"},
        )
        assert changed_policy.status_code == 200
        stale = client.post(
            f"/api/datasets/{dataset_id}/directory-export-jobs",
            json={"plan_id": fresh["plan_id"], "plan_hash": fresh["plan_hash"]},
        )
        assert stale.status_code == 409

        invalid = client.get(
            f"/api/datasets/{dataset_id}/directory-export-previews/../../escape"
        )
        assert invalid.status_code in {404, 422}

    engine.dispose()


def test_cancelled_directory_export_cleans_workspace_and_retry_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'cancel-directory-export.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    plan_root = tmp_path / "plans"
    output_root = tmp_path / "managed-exports"
    monkeypatch.setattr(directory_export_service, "directory_export_plan_root", lambda: plan_root)
    monkeypatch.setattr(directory_export_service, "directory_export_output_root", lambda: output_root)
    app = _make_app(engine)
    entered = threading.Event()
    release = threading.Event()
    original_copy = directory_export_job_service._copy_verified

    with TestClient(app) as client:
        dataset_id, samples = _create_dataset(client, tmp_path / "raw")
        _prepare_triage(client, dataset_id, samples)
        preview = client.post(
            f"/api/datasets/{dataset_id}/directory-export-previews",
            json={"delivery": "directory"},
        ).json()
        created = client.post(
            f"/api/datasets/{dataset_id}/directory-export-jobs",
            json={"plan_id": preview["plan_id"], "plan_hash": preview["plan_hash"]},
        ).json()
        job_id = created["job"]["id"]

        def blocked_copy(source, destination, *, expected_hash, checkpoint):
            destination.write(b"partial")
            entered.set()
            assert release.wait(timeout=3)
            checkpoint()
            raise AssertionError("checkpoint should have cancelled the job")

        monkeypatch.setattr(directory_export_job_service, "_copy_verified", blocked_copy)
        runner = _runner(engine)
        assert runner.start() is True
        assert entered.wait(timeout=3)
        with Session(engine) as session:
            requested = job_service.request_job_cancel(session, job_id)
            assert requested.status == "running"
        release.set()
        cancelled = _wait_for_terminal(engine, job_id)
        assert cancelled.status == "cancelled"
        assert not list(output_root.glob(".*.part"))
        assert not (output_root / preview["output_name"]).exists()

        monkeypatch.setattr(directory_export_job_service, "_copy_verified", original_copy)
        retried = client.post(f"/api/jobs/{job_id}/retry")
        assert retried.status_code == 201
        completed = _wait_for_terminal(engine, retried.json()["id"])
        assert completed.status == "succeeded"
        assert Path(completed.result["output_path"]).is_dir()
        assert runner.stop() is True

    engine.dispose()
