from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.api import datasets, jobs, samples, triage, triage_directory_mapping
from app.core.database import get_session
from app.models.sample import Sample
from app.services import (
    job_service,
    triage_directory_mapping_job_service,
    triage_directory_mapping_service,
)
from app.services.job_runner import JobRunner


def _make_app(engine) -> FastAPI:
    app = FastAPI()
    app.include_router(datasets.router)
    app.include_router(samples.router)
    app.include_router(triage.router)
    app.include_router(triage_directory_mapping.router)
    app.include_router(jobs.router)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


def _runner(engine) -> JobRunner:
    runner = JobRunner(engine)
    runner.register_handler(
        triage_directory_mapping_job_service.TRIAGE_DIRECTORY_MAPPING_JOB_TYPE,
        triage_directory_mapping_job_service.run_triage_directory_mapping_job,
    )
    return runner


def _create_dataset(client: TestClient, raw_root: Path) -> tuple[int, dict[str, dict]]:
    content = b"\x89PNG\r\n\x1a\nlegacy-directory-mapping"
    paths = [
        "OK/old-clear.png",
        "OK/old-borderline.png",
        "NG/scratch/severe/ng.png",
        "review/pending.png",
        "root.png",
    ]
    for index, relative in enumerate(paths):
        path = raw_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content + bytes([index]))
    created = client.post(
        "/api/datasets",
        json={"name": "Legacy folders", "root_path": str(raw_root)},
    )
    assert created.status_code == 201
    dataset_id = created.json()["id"]
    scanned = client.post(
        f"/api/datasets/{dataset_id}/scan",
        json={"folder_path": str(raw_root)},
    )
    assert scanned.status_code == 200
    listed = client.get(
        f"/api/datasets/{dataset_id}/samples",
        params={"page_size": 20, "sort_by": "relative_path", "sort_order": "asc"},
    )
    assert listed.status_code == 200
    return dataset_id, {item["relative_path"]: item for item in listed.json()["items"]}


def _triage_payload(sample: dict, **values) -> dict:
    return {
        "expected_version": sample["triage_version"],
        "expected_file_hash": sample["file_hash"],
        "triage_status": values["triage_status"],
        "ok_grade": values.get("ok_grade"),
        "defect_severity": values.get("defect_severity"),
        "defect_type_ids": values.get("defect_type_ids", []),
        "primary_defect_type_id": values.get("primary_defect_type_id"),
        "triage_note": values.get("triage_note"),
    }


def test_directory_mapping_preview_requires_explicit_ok_grade_and_imports_atomically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'mapping.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    plan_root = tmp_path / "plans"
    monkeypatch.setattr(
        triage_directory_mapping_service,
        "triage_directory_mapping_plan_root",
        lambda: plan_root,
    )
    app = _make_app(engine)

    with TestClient(app) as client:
        dataset_id, samples = _create_dataset(client, tmp_path / "raw")
        scratch = client.post(
            f"/api/datasets/{dataset_id}/defect-types",
            json={"name": "划痕", "code": "scratch"},
        ).json()
        existing = samples["OK/old-borderline.png"]
        saved = client.put(
            f"/api/samples/{existing['id']}/triage",
            json=_triage_payload(
                existing,
                triage_status="ok",
                ok_grade="borderline",
                triage_note="人工已确认",
            ),
        )
        assert saved.status_code == 200

        sources = client.get(
            f"/api/datasets/{dataset_id}/triage-directory-sources",
            params={"page": 1, "page_size": 2},
        )
        assert sources.status_code == 200
        source_data = sources.json()
        assert source_data["total_directories"] == 4
        assert source_data["total_images"] == 5
        assert source_data["page_count"] == 2
        assert source_data["triage_policy"]["split_ok"] is True
        assert source_data["defect_types"][0]["code"] == "scratch"
        searched = client.get(
            f"/api/datasets/{dataset_id}/triage-directory-sources",
            params={"search": "scratch"},
        ).json()
        assert [item["directory"] for item in searched["items"]] == ["NG/scratch/severe"]

        missing_grade = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-previews",
            json={
                "mappings": [{"source_directory": "OK", "triage_status": "ok"}],
            },
        )
        assert missing_grade.status_code == 422
        assert "完全 OK 或勉强 OK" in missing_grade.json()["detail"]

        preview = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-previews",
            json={
                "existing_behavior": "skip",
                "mappings": [
                    {
                        "source_directory": "OK",
                        "triage_status": "ok",
                        "ok_grade": "clear",
                    },
                    {
                        "source_directory": "NG/scratch/severe",
                        "triage_status": "ng",
                        "defect_type_id": scratch["id"],
                        "defect_severity": "severe",
                    },
                    {"source_directory": "review", "triage_status": "pending"},
                ],
            },
        )
        assert preview.status_code == 201
        plan = preview.json()
        assert plan["total_images"] == 5
        assert plan["mapped_sample_count"] == 4
        assert plan["change_count"] == 3
        assert plan["skipped_existing_count"] == 1
        assert plan["unmapped_count"] == 1
        assert len(plan["plan_hash"]) == 64
        assert plan_root.joinpath(f"plan-{plan['plan_id']}.json").is_file()

        before_revision = client.get(f"/api/datasets/{dataset_id}").json()["revision"]
        created = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-jobs",
            json={"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]},
        )
        assert created.status_code == 201
        job_id = created.json()["job"]["id"]
        assert set(created.json()["job"]["parameters"]) == {
            "plan_id",
            "plan_hash",
            "change_count",
            "request_fingerprint",
        }
        duplicate = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-jobs",
            json={"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["job"]["id"] == job_id
        assert _runner(engine).run_once() is True
        completed = client.get(f"/api/jobs/{job_id}").json()
        assert completed["status"] == "succeeded"
        assert completed["result"]["changed_sample_count"] == 3
        assert client.get(f"/api/datasets/{dataset_id}").json()["revision"] == before_revision + 1

        clear = client.get(f"/api/samples/{samples['OK/old-clear.png']['id']}/triage").json()
        assert (clear["triage_status"], clear["ok_grade"]) == ("ok", "clear")
        preserved = client.get(
            f"/api/samples/{samples['OK/old-borderline.png']['id']}/triage"
        ).json()
        assert (preserved["ok_grade"], preserved["triage_note"]) == (
            "borderline",
            "人工已确认",
        )
        ng = client.get(f"/api/samples/{samples['NG/scratch/severe/ng.png']['id']}/triage").json()
        assert ng["triage_status"] == "ng"
        assert ng["defect_severity"] == "severe"
        assert [item["code"] for item in ng["defect_types"]] == ["scratch"]
        pending = client.get(f"/api/samples/{samples['review/pending.png']['id']}/triage").json()
        assert pending["triage_status"] == "pending"
        root = client.get(f"/api/samples/{samples['root.png']['id']}/triage").json()
        assert root["triage_status"] == "untriaged"

    engine.dispose()


def test_directory_mapping_overwrite_and_stale_plan_are_guarded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'mapping-conflict.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        triage_directory_mapping_service,
        "triage_directory_mapping_plan_root",
        lambda: tmp_path / "plans",
    )
    app = _make_app(engine)

    with TestClient(app) as client:
        dataset_id, samples = _create_dataset(client, tmp_path / "raw")
        first = samples["OK/old-borderline.png"]
        assert client.put(
            f"/api/samples/{first['id']}/triage",
            json=_triage_payload(first, triage_status="ok", ok_grade="borderline"),
        ).status_code == 200
        preview = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-previews",
            json={
                "existing_behavior": "overwrite",
                "mappings": [
                    {
                        "source_directory": "OK",
                        "triage_status": "ok",
                        "ok_grade": "clear",
                    }
                ],
            },
        ).json()
        assert preview["change_count"] == 2
        changed = client.put(
            f"/api/samples/{samples['root.png']['id']}/triage",
            json=_triage_payload(samples["root.png"], triage_status="pending"),
        )
        assert changed.status_code == 200
        stale = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-jobs",
            json={"plan_id": preview["plan_id"], "plan_hash": preview["plan_hash"]},
        )
        assert stale.status_code == 409

        fresh = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-previews",
            json={
                "existing_behavior": "overwrite",
                "mappings": [
                    {
                        "source_directory": "OK",
                        "triage_status": "ok",
                        "ok_grade": "clear",
                    }
                ],
            },
        ).json()
        created = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-jobs",
            json={"plan_id": fresh["plan_id"], "plan_hash": fresh["plan_hash"]},
        ).json()
        untouched_id = samples["OK/old-clear.png"]["id"]
        with Session(engine) as session:
            raced = session.get(Sample, first["id"])
            assert raced is not None
            raced.triage_version += 1
            session.add(raced)
            session.commit()
        assert _runner(engine).run_once() is True
        failed = client.get(f"/api/jobs/{created['job']['id']}").json()
        assert failed["status"] == "failed"
        assert "预览后发生变化" in failed["error"]["message"]
        untouched = client.get(f"/api/samples/{untouched_id}/triage").json()
        assert untouched["triage_status"] == "untriaged"

        unsafe = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-previews",
            json={
                "mappings": [
                    {
                        "source_directory": "../OK",
                        "triage_status": "ok",
                        "ok_grade": "clear",
                    }
                ]
            },
        )
        assert unsafe.status_code == 422

    engine.dispose()


def test_directory_mapping_respects_unified_ok_and_queued_cancel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'mapping-unified.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        triage_directory_mapping_service,
        "triage_directory_mapping_plan_root",
        lambda: tmp_path / "plans",
    )
    app = _make_app(engine)

    with TestClient(app) as client:
        dataset_id, samples = _create_dataset(client, tmp_path / "raw")
        policy = client.get(f"/api/datasets/{dataset_id}/triage-policy").json()
        configured = client.put(
            f"/api/datasets/{dataset_id}/triage-policy",
            json={**policy, "split_ok": False, "ng_grouping": "none"},
        )
        assert configured.status_code == 200
        preview = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-previews",
            json={
                "mappings": [{"source_directory": "OK", "triage_status": "ok"}],
            },
        )
        assert preview.status_code == 201
        assert preview.json()["change_count"] == 2
        invalid_grade = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-previews",
            json={
                "mappings": [
                    {
                        "source_directory": "OK",
                        "triage_status": "ok",
                        "ok_grade": "clear",
                    }
                ]
            },
        )
        assert invalid_grade.status_code == 422
        created = client.post(
            f"/api/datasets/{dataset_id}/triage-directory-mapping-jobs",
            json={
                "plan_id": preview.json()["plan_id"],
                "plan_hash": preview.json()["plan_hash"],
            },
        ).json()
        cancelled = client.post(f"/api/jobs/{created['job']['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        for relative in ("OK/old-clear.png", "OK/old-borderline.png"):
            triage_data = client.get(f"/api/samples/{samples[relative]['id']}/triage").json()
            assert triage_data["triage_status"] == "untriaged"

    engine.dispose()
