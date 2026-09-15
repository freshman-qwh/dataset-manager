from pathlib import Path
import base64

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.models.defect_type import DefectType
from app.schemas.triage import TriagePolicyValues
from app.services.triage_service import configured_export_bucket


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def make_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def create_image_dataset(client: TestClient, tmp_path: Path) -> tuple[dict, dict[str, dict]]:
    root = tmp_path / "triage-images"
    root.mkdir(parents=True)
    for name in ("a.png", "b.png", "c.png"):
        (root / name).write_bytes(PNG_1X1)
    dataset = client.post(
        "/api/datasets",
        json={"name": "Triage", "root_path": str(root)},
    ).json()
    scanned = client.post(
        f"/api/datasets/{dataset['id']}/scan",
        json={"folder_path": str(root)},
    )
    assert scanned.status_code == 200
    samples = client.get(
        f"/api/datasets/{dataset['id']}/samples",
        params={"page_size": 20},
    ).json()["items"]
    return dataset, {item["filename"]: item for item in samples}


def triage_payload(sample: dict, **overrides: object) -> dict:
    payload = {
        "expected_version": sample["triage_version"],
        "expected_file_hash": sample["file_hash"],
        "triage_status": "untriaged",
        "ok_grade": None,
        "defect_severity": None,
        "defect_type_ids": [],
        "primary_defect_type_id": None,
        "triage_note": None,
    }
    payload.update(overrides)
    return payload


def test_quick_triage_api_workflow_and_conflict_protection(tmp_path: Path) -> None:
    with make_client() as client:
        dataset, samples = create_image_dataset(client, tmp_path)
        dataset_id = dataset["id"]

        policy = client.get(f"/api/datasets/{dataset_id}/triage-policy")
        assert policy.status_code == 200
        assert policy.json()["version"] == 1

        parent = client.post(
            f"/api/datasets/{dataset_id}/defect-types",
            json={"name": "表面", "code": "surface"},
        )
        assert parent.status_code == 201
        child = client.post(
            f"/api/datasets/{dataset_id}/defect-types",
            json={
                "name": "划痕",
                "code": "scratch",
                "parent_id": parent.json()["id"],
            },
        )
        assert child.status_code == 201
        grandchild = client.post(
            f"/api/datasets/{dataset_id}/defect-types",
            json={
                "name": "细划痕",
                "code": "thin-scratch",
                "parent_id": child.json()["id"],
            },
        )
        assert grandchild.status_code == 422

        invalid_clear = client.put(
            f"/api/samples/{samples['a.png']['id']}/triage",
            json=triage_payload(
                samples["a.png"],
                triage_status="ok",
                ok_grade="clear",
                defect_severity="mild",
            ),
        )
        assert invalid_clear.status_code == 422

        clear = client.put(
            f"/api/samples/{samples['a.png']['id']}/triage",
            json=triage_payload(
                samples["a.png"],
                triage_status="ok",
                ok_grade="clear",
            ),
        )
        assert clear.status_code == 200
        assert clear.json()["triage_version"] == 1
        assert clear.json()["outdated"] is False

        no_change_revision = client.get(f"/api/datasets/{dataset_id}").json()["revision"]
        no_change = client.put(
            f"/api/samples/{samples['a.png']['id']}/triage",
            json={
                **triage_payload(
                    samples["a.png"],
                    triage_status="ok",
                    ok_grade="clear",
                ),
                "expected_version": 1,
            },
        )
        assert no_change.status_code == 200
        assert no_change.json()["triage_version"] == 1
        assert client.get(f"/api/datasets/{dataset_id}").json()["revision"] == no_change_revision

        stale = client.put(
            f"/api/samples/{samples['a.png']['id']}/triage",
            json=triage_payload(
                samples["a.png"],
                triage_status="ok",
                ok_grade="borderline",
            ),
        )
        assert stale.status_code == 409

        borderline = client.put(
            f"/api/samples/{samples['b.png']['id']}/triage",
            json=triage_payload(
                samples["b.png"],
                triage_status="ok",
                ok_grade="borderline",
                defect_severity="mild",
                defect_type_ids=[child.json()["id"]],
                primary_defect_type_id=child.json()["id"],
                triage_note="客户允许",
            ),
        )
        assert borderline.status_code == 200
        assert borderline.json()["defect_types"][0]["name"] == "划痕"

        navigation = client.get(
            f"/api/datasets/{dataset_id}/triage/navigation",
            params={"queue_scope": "untriaged"},
        )
        assert navigation.status_code == 200
        assert navigation.json()["total"] == 1
        assert navigation.json()["current_sample"]["filename"] == "c.png"

        pending = client.put(
            f"/api/samples/{samples['c.png']['id']}/triage",
            json=triage_payload(samples["c.png"], triage_status="pending"),
        )
        assert pending.status_code == 200
        pending_navigation = client.get(
            f"/api/datasets/{dataset_id}/triage/navigation",
            params={"queue_scope": "pending"},
        ).json()
        assert pending_navigation["total"] == 1
        assert pending_navigation["current_sample"]["filename"] == "c.png"

        ng = client.put(
            f"/api/samples/{samples['c.png']['id']}/triage",
            json={
                **triage_payload(
                    samples["c.png"],
                    triage_status="ng",
                    defect_severity="severe",
                ),
                "expected_version": pending.json()["triage_version"],
            },
        )
        assert ng.status_code == 200

        ok_samples = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"triage_status": "ok", "page_size": 20},
        ).json()
        assert ok_samples["total"] == 2
        scratch_samples = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"defect_type_id": child.json()["id"], "page_size": 20},
        ).json()
        assert [item["filename"] for item in scratch_samples["items"]] == ["b.png"]

        stats = client.get(f"/api/datasets/{dataset_id}/triage/stats").json()
        assert stats["by_status"] == {"ng": 1, "ok": 2}
        assert stats["by_ok_grade"] == {"borderline": 1, "clear": 1}
        assert stats["by_defect_type"] == {"划痕": 1}
        assert stats["outdated"] == 0

        updated_policy = client.put(
            f"/api/datasets/{dataset_id}/triage-policy",
            json={
                **policy.json(),
                "instructions": "按客户第二版标准判断",
            },
        )
        assert updated_policy.status_code == 200
        assert updated_policy.json()["version"] == 2
        assert client.get(f"/api/datasets/{dataset_id}/triage/stats").json()["outdated"] == 3
        outdated = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"triage_outdated": True, "page_size": 20},
        ).json()
        assert outdated["total"] == 3

        manifest = client.get(f"/api/datasets/{dataset_id}/export-manifest").json()
        by_filename = {item["filename"]: item for item in manifest["samples"]}
        assert by_filename["b.png"]["triage"]["defect_types"][0]["code"] == "scratch"
        assert by_filename["c.png"]["triage"]["defect_severity"] == "severe"

        deleted = client.delete(f"/api/datasets/{dataset_id}")
        assert deleted.status_code == 204

    app.dependency_overrides.clear()


def test_triage_rejects_cross_dataset_or_inactive_defect_types(tmp_path: Path) -> None:
    with make_client() as client:
        first, first_samples = create_image_dataset(client, tmp_path / "first")
        second, _ = create_image_dataset(client, tmp_path / "second")
        foreign_type = client.post(
            f"/api/datasets/{second['id']}/defect-types",
            json={"name": "Foreign", "code": "foreign"},
        ).json()
        rejected = client.put(
            f"/api/samples/{first_samples['a.png']['id']}/triage",
            json=triage_payload(
                first_samples["a.png"],
                triage_status="ng",
                defect_type_ids=[foreign_type["id"]],
                primary_defect_type_id=foreign_type["id"],
            ),
        )
        assert rejected.status_code == 422

        local_type = client.post(
            f"/api/datasets/{first['id']}/defect-types",
            json={"name": "Inactive", "code": "inactive"},
        ).json()
        disabled = client.patch(
            f"/api/datasets/{first['id']}/defect-types/{local_type['id']}",
            json={"is_active": False},
        )
        assert disabled.status_code == 200
        rejected_inactive = client.put(
            f"/api/samples/{first_samples['a.png']['id']}/triage",
            json=triage_payload(
                first_samples["a.png"],
                triage_status="ng",
                defect_type_ids=[local_type["id"]],
                primary_defect_type_id=local_type["id"],
            ),
        )
        assert rejected_inactive.status_code == 422

    app.dependency_overrides.clear()


def test_triage_hierarchy_configuration_controls_validation_filters_and_export(
    tmp_path: Path,
) -> None:
    with make_client() as client:
        dataset, samples = create_image_dataset(client, tmp_path)
        dataset_id = dataset["id"]
        scratch = client.post(
            f"/api/datasets/{dataset_id}/defect-types",
            json={"name": "划痕", "code": "scratch"},
        ).json()

        policy = client.get(f"/api/datasets/{dataset_id}/triage-policy").json()
        assert policy["split_ok"] is True
        assert policy["ng_grouping"] == "defect_type_and_severity"

        clear = client.put(
            f"/api/samples/{samples['a.png']['id']}/triage",
            json=triage_payload(
                samples["a.png"],
                triage_status="ok",
                ok_grade="clear",
            ),
        )
        assert clear.status_code == 200
        detailed_ng = client.put(
            f"/api/samples/{samples['b.png']['id']}/triage",
            json=triage_payload(
                samples["b.png"],
                triage_status="ng",
                defect_type_ids=[scratch["id"]],
                primary_defect_type_id=scratch["id"],
                defect_severity="mild",
            ),
        )
        assert detailed_ng.status_code == 200

        configured = client.put(
            f"/api/datasets/{dataset_id}/triage-policy",
            json={
                **policy,
                "split_ok": False,
                "ng_grouping": "defect_type",
            },
        )
        assert configured.status_code == 200
        assert configured.json()["version"] == policy["version"] + 1

        existing = client.get(
            f"/api/samples/{samples['b.png']['id']}/triage"
        ).json()
        assert existing["defect_severity"] == "mild"
        assert existing["defect_types"][0]["code"] == "scratch"
        assert existing["outdated"] is True

        graded_ok = client.put(
            f"/api/samples/{samples['c.png']['id']}/triage",
            json=triage_payload(
                samples["c.png"],
                triage_status="ok",
                ok_grade="clear",
            ),
        )
        assert graded_ok.status_code == 422
        unified_ok = client.put(
            f"/api/samples/{samples['c.png']['id']}/triage",
            json=triage_payload(samples["c.png"], triage_status="ok"),
        )
        assert unified_ok.status_code == 200
        assert unified_ok.json()["ok_grade"] is None

        severity_not_enabled = client.put(
            f"/api/samples/{samples['b.png']['id']}/triage",
            json={
                **triage_payload(
                    samples["b.png"],
                    triage_status="ng",
                    defect_type_ids=[scratch["id"]],
                    primary_defect_type_id=scratch["id"],
                    defect_severity="severe",
                ),
                "expected_version": detailed_ng.json()["triage_version"],
            },
        )
        assert severity_not_enabled.status_code == 422
        category_only = client.put(
            f"/api/samples/{samples['b.png']['id']}/triage",
            json={
                **triage_payload(
                    samples["b.png"],
                    triage_status="ng",
                    defect_type_ids=[scratch["id"]],
                    primary_defect_type_id=scratch["id"],
                ),
                "expected_version": detailed_ng.json()["triage_version"],
            },
        )
        assert category_only.status_code == 200

        assert client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"ok_grade": "clear"},
        ).status_code == 422
        assert client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"defect_severity": "mild"},
        ).status_code == 422
        category_filter = client.get(
            f"/api/datasets/{dataset_id}/samples",
            params={"defect_type_id": scratch["id"]},
        )
        assert category_filter.status_code == 200
        assert category_filter.json()["total"] == 1

        navigation_filter = client.get(
            f"/api/datasets/{dataset_id}/triage/navigation",
            params={
                "queue_scope": "current_filter",
                "defect_severity": "mild",
            },
        )
        assert navigation_filter.status_code == 422

        stats = client.get(f"/api/datasets/{dataset_id}/triage/stats").json()
        assert stats["by_export_bucket"] == {"ng/scratch": 1, "ok": 2}
        manifest = client.get(f"/api/datasets/{dataset_id}/export-manifest").json()
        assert manifest["dataset"]["triage_policy"]["split_ok"] is False
        by_filename = {item["filename"]: item for item in manifest["samples"]}
        assert by_filename["a.png"]["triage"]["export_bucket"] == "ok"
        assert by_filename["b.png"]["triage"]["export_bucket"] == "ng/scratch"

    app.dependency_overrides.clear()


def test_configured_export_bucket_covers_every_hierarchy_and_legacy_values() -> None:
    scratch = DefectType(id=7, dataset_id=1, name="划痕", code="scratch")
    dent = DefectType(id=8, dataset_id=1, name="凹陷", code="dent")

    legacy_policy = TriagePolicyValues.model_validate(
        {"instructions": "旧版策略没有层级字段"}
    )
    assert legacy_policy.split_ok is True
    assert legacy_policy.ng_grouping == "defect_type_and_severity"

    base = {
        "triage_status": "ng",
        "ok_grade": None,
        "defect_severity": "mild",
        "defect_types": [scratch],
        "primary_defect_type_id": scratch.id,
    }
    assert configured_export_bucket(
        legacy_policy.model_copy(update={"ng_grouping": "none"}), **base
    ) == "ng"
    assert configured_export_bucket(
        legacy_policy.model_copy(update={"ng_grouping": "defect_type"}), **base
    ) == "ng/scratch"
    assert configured_export_bucket(
        legacy_policy.model_copy(update={"ng_grouping": "severity"}), **base
    ) == "ng/mild"
    assert configured_export_bucket(legacy_policy, **base) == "ng/scratch/mild"
    assert configured_export_bucket(
        legacy_policy,
        **{
            **base,
            "defect_types": [scratch, dent],
            "primary_defect_type_id": None,
            "defect_severity": None,
        },
    ) == "ng/multi_defect/ungraded"
    assert configured_export_bucket(
        legacy_policy,
        **{
            **base,
            "defect_types": [],
            "primary_defect_type_id": None,
            "defect_severity": None,
        },
    ) == "ng/unknown/ungraded"
    assert configured_export_bucket(
        legacy_policy,
        triage_status="ok",
        ok_grade=None,
        defect_severity=None,
        defect_types=[],
        primary_defect_type_id=None,
    ) == "ok/ungraded"
    assert configured_export_bucket(
        legacy_policy.model_copy(update={"split_ok": False}),
        triage_status="ok",
        ok_grade="clear",
        defect_severity=None,
        defect_types=[],
        primary_defect_type_id=None,
    ) == "ok"
