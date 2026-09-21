"""Add quick-triage onboarding state and preserve legacy policy semantics."""

from collections.abc import Sequence
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260921_0007"
down_revision: str | Sequence[str] | None = "20260915_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_POLICY = {
    "split_ok": True,
    "ng_grouping": "defect_type_and_severity",
    "instructions": "",
    "clear_ok_definition": "无可见缺陷，可作为纯正常样本候选。",
    "borderline_ok_definition": "存在可接受瑕疵，但按当前客户标准仍判定合格。",
    "mild_definition": "轻微且局部。",
    "moderate_definition": "明显但未达到严重程度。",
    "severe_definition": "明显影响质量或使用。",
}


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("datasets")}
    if "triage_onboarding_completed" not in columns:
        op.add_column(
            "datasets",
            sa.Column(
                "triage_onboarding_completed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    processed_exists = (
        "EXISTS (SELECT 1 FROM samples "
        "WHERE samples.dataset_id = datasets.id "
        "AND samples.file_type = 'image' "
        "AND samples.triage_status <> 'untriaged')"
    )
    processed_policies = bind.execute(
        sa.text(
            "SELECT id, triage_policy_json FROM datasets "
            f"WHERE {processed_exists}"
        )
    ).fetchall()
    for dataset_id, raw_policy in processed_policies:
        try:
            parsed = json.loads(raw_policy) if raw_policy else {}
        except (TypeError, ValueError):
            parsed = {}
        has_explicit_hierarchy = (
            isinstance(parsed, dict)
            and isinstance(parsed.get("split_ok"), bool)
            and parsed.get("ng_grouping")
            in {"none", "defect_type", "severity", "defect_type_and_severity"}
        )
        if has_explicit_hierarchy:
            continue
        preserved_policy = {
            **LEGACY_POLICY,
            **(parsed if isinstance(parsed, dict) else {}),
            "split_ok": True,
            "ng_grouping": "defect_type_and_severity",
        }
        bind.execute(
            sa.text(
                "UPDATE datasets SET triage_policy_json = :policy "
                "WHERE id = :dataset_id"
            ),
            {
                "dataset_id": dataset_id,
                "policy": json.dumps(
                    preserved_policy,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        )
    bind.execute(
        sa.text(
            "UPDATE datasets SET triage_onboarding_completed = 1 "
            f"WHERE {processed_exists}"
        )
    )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in inspect(op.get_bind()).get_columns("datasets")
    }
    if "triage_onboarding_completed" in columns:
        op.drop_column("datasets", "triage_onboarding_completed")
