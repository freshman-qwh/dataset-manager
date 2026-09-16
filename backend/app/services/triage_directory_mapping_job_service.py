from __future__ import annotations

from datetime import timezone

from pydantic import ValidationError
from sqlalchemy import delete, text
from sqlmodel import Session, select

from app.models.dataset import Dataset, utc_now
from app.models.defect_type import SampleDefectLink
from app.models.sample import Sample
from app.schemas.job import JobCreate
from app.schemas.triage_directory_mapping import (
    TriageDirectoryMappingJobCreateRequest,
    TriageDirectoryMappingJobCreateResponse,
    TriageDirectoryMappingJobParameters,
)
from app.services import (
    dataset_service,
    job_service,
    triage_directory_mapping_service,
)
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.job_runner import JobContext


TRIAGE_DIRECTORY_MAPPING_JOB_TYPE = "triage.directory_mapping_import"


def create_triage_directory_mapping_job(
    session: Session,
    dataset_id: int,
    payload: TriageDirectoryMappingJobCreateRequest,
) -> TriageDirectoryMappingJobCreateResponse:
    job_service.ensure_jobs_schema(session)
    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    plan = triage_directory_mapping_service.validate_plan_for_job(
        session,
        dataset_id,
        payload.plan_id,
        payload.plan_hash,
    )
    change_count = int(plan["change_count"])
    if change_count <= 0:
        raise triage_directory_mapping_service.TriageDirectoryMappingError(
            "当前计划没有需要写入的分拣结果。"
        )
    parameters = TriageDirectoryMappingJobParameters(
        plan_id=payload.plan_id,
        plan_hash=payload.plan_hash,
        change_count=change_count,
        request_fingerprint=payload.plan_hash,
    ).model_dump(mode="json")

    session.commit()
    session.exec(text("BEGIN IMMEDIATE"))
    active = job_service.find_active_job(
        session,
        job_type=TRIAGE_DIRECTORY_MAPPING_JOB_TYPE,
        dataset_id=dataset_id,
        parameter_match=("request_fingerprint", payload.plan_hash),
    )
    if active is not None:
        session.commit()
        return TriageDirectoryMappingJobCreateResponse(job=active, created=False)
    created = job_service.create_job(
        session,
        JobCreate(
            job_type=TRIAGE_DIRECTORY_MAPPING_JOB_TYPE,
            title=f"导入旧目录分拣：{dataset.name}",
            dataset_id=dataset_id,
            parameters=parameters,
            progress_total=change_count,
        ),
    )
    return TriageDirectoryMappingJobCreateResponse(job=created, created=True)


def run_triage_directory_mapping_job(
    context: JobContext,
    parameters: dict[str, object],
) -> dict[str, object]:
    try:
        snapshot = TriageDirectoryMappingJobParameters.model_validate(parameters)
    except ValidationError as exc:
        raise job_service.JobStateError(
            f"Invalid triage directory mapping parameter snapshot: {exc}"
        ) from exc
    plan = triage_directory_mapping_service.load_triage_directory_mapping_plan(
        snapshot.plan_id,
        expected_hash=snapshot.plan_hash,
    )
    if int(plan["change_count"]) != snapshot.change_count:
        raise job_service.JobStateError("旧目录映射计划的变更数量不一致。")
    apply_items = _apply_items(plan)
    context.report_progress(
        current=0,
        total=len(apply_items),
        stage="validating_mapping",
    )
    _validate_current_state(context, plan, apply_items)
    context.checkpoint()
    context.report_progress(
        current=0,
        total=len(apply_items),
        stage="applying_mapping",
    )
    _apply_atomically(context, plan, apply_items)
    context.report_progress(
        current=len(apply_items),
        total=len(apply_items),
        stage="finalizing",
    )
    return {
        "plan_id": snapshot.plan_id,
        "plan_hash": snapshot.plan_hash,
        "mapped_sample_count": int(plan["mapped_sample_count"]),
        "changed_sample_count": len(apply_items),
        "unchanged_count": int(plan["unchanged_count"]),
        "skipped_existing_count": int(plan["skipped_existing_count"]),
        "unmapped_count": int(plan["unmapped_count"]),
        "unavailable_count": int(plan["unavailable_count"]),
        "existing_behavior": plan["existing_behavior"],
    }


def _apply_items(plan: dict[str, object]) -> list[dict[str, object]]:
    items = plan.get("items")
    if not isinstance(items, list):
        raise job_service.JobStateError("旧目录映射计划缺少样本列表。")
    selected = [item for item in items if isinstance(item, dict) and item.get("decision") == "apply"]
    if len(selected) != int(plan["change_count"]):
        raise job_service.JobStateError("旧目录映射计划的样本数量不一致。")
    return selected


def _validate_current_state(
    context: JobContext,
    plan: dict[str, object],
    items: list[dict[str, object]],
) -> None:
    with Session(context.engine) as session:
        _validate_dataset(session, plan)
        sample_ids = [int(item["sample_id"]) for item in items]
        samples = {
            sample.id: sample
            for sample in session.exec(select(Sample).where(Sample.id.in_(sample_ids))).all()
        }
        for item in items:
            sample = samples.get(int(item["sample_id"]))
            if sample is None or sample.dataset_id != int(plan["dataset_id"]):
                raise triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError(
                    "预览中的样本已被删除或移动，请重新预览。"
                )
            if (
                sample.triage_version != int(item["expected_triage_version"])
                or sample.file_hash != str(item["expected_file_hash"])
                or sample.file_status != "normal"
            ):
                raise triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError(
                    f"样本在预览后发生变化：{sample.filename}"
                )


def _apply_atomically(
    context: JobContext,
    plan: dict[str, object],
    items: list[dict[str, object]],
) -> None:
    with Session(context.engine) as session:
        try:
            session.exec(text("BEGIN IMMEDIATE"))
            _validate_dataset(session, plan)
            sample_ids = [int(item["sample_id"]) for item in items]
            samples = {
                sample.id: sample
                for sample in session.exec(select(Sample).where(Sample.id.in_(sample_ids))).all()
            }
            for item in items:
                sample_id = int(item["sample_id"])
                sample = samples.get(sample_id)
                if sample is None or sample.dataset_id != int(plan["dataset_id"]):
                    raise triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError(
                        "预览中的样本已被删除或移动，请重新预览。"
                    )
                if (
                    sample.triage_version != int(item["expected_triage_version"])
                    or sample.file_hash != str(item["expected_file_hash"])
                    or sample.file_status != "normal"
                ):
                    raise triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError(
                        f"样本在预览后发生变化：{sample.filename}"
                    )

            now = utc_now().astimezone(timezone.utc)
            for item in items:
                sample_id = int(item["sample_id"])
                sample = samples[sample_id]
                sample.triage_status = str(item["target_status"])
                sample.ok_grade = _optional_string(item.get("target_ok_grade"))
                sample.defect_severity = _optional_string(
                    item.get("target_defect_severity")
                )
                primary = item.get("target_defect_type_id")
                sample.primary_defect_type_id = int(primary) if primary is not None else None
                sample.triage_note = _optional_string(item.get("triage_note"))
                sample.triage_version += 1
                sample.triaged_at = now
                sample.triage_policy_version = int(plan["triage_policy_version"])
                sample.triaged_file_hash = sample.file_hash
                sample.updated_at = now
                session.add(sample)
                session.exec(
                    delete(SampleDefectLink).where(SampleDefectLink.sample_id == sample_id)
                )
                for defect_type_id in item.get("target_defect_type_ids", []):
                    session.add(
                        SampleDefectLink(
                            sample_id=sample_id,
                            defect_type_id=int(defect_type_id),
                        )
                    )
            bump_dataset_revision(session, int(plan["dataset_id"]))
            session.commit()
        except BaseException:
            session.rollback()
            raise


def _validate_dataset(session: Session, plan: dict[str, object]) -> None:
    dataset = session.get(Dataset, int(plan["dataset_id"]))
    if dataset is None:
        raise triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError(
            "数据集已不存在。"
        )
    if dataset.revision != int(plan["dataset_revision"]):
        raise triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError(
            "预览后数据集已变化，请重新预览。"
        )
    if dataset.triage_policy_version != int(plan["triage_policy_version"]):
        raise triage_directory_mapping_service.TriageDirectoryMappingPlanChangedError(
            "预览后分拣层级已变化，请重新预览。"
        )


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None
