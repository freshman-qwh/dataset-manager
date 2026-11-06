"""Preserve existing records while introducing projects, categories and batches."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_0014"
down_revision = "20261101_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("projects"):
        op.create_table("projects",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.String(2000), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("name", name="uq_projects_name"))
        op.create_index("ix_projects_name", "projects", ["name"])
    if not sa.inspect(bind).has_table("dataset_categories"):
        op.create_table("dataset_categories",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("dataset_id", sa.Integer, sa.ForeignKey("datasets.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.String(2000), nullable=True),
            sa.UniqueConstraint("dataset_id", "name", name="uq_dataset_categories_name"))
        op.create_index("ix_dataset_categories_dataset_id", "dataset_categories", ["dataset_id"])
    if not sa.inspect(bind).has_table("dataset_batches"):
        op.create_table("dataset_batches",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("dataset_id", sa.Integer, sa.ForeignKey("datasets.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("code", sa.String(160), nullable=False),
            sa.Column("captured_at", sa.String(80), nullable=True),
            sa.Column("notes", sa.String(2000), nullable=True),
            sa.UniqueConstraint("dataset_id", "code", name="uq_dataset_batches_code"))
        op.create_index("ix_dataset_batches_dataset_id", "dataset_batches", ["dataset_id"])

    # SQLite supports nullable REFERENCES columns without rewriting old tables.
    # This keeps annotation links, frozen records and row identities untouched.
    dataset_columns = {row["name"] for row in sa.inspect(bind).get_columns("datasets")}
    if "project_id" not in dataset_columns:
        op.execute("ALTER TABLE datasets ADD COLUMN project_id INTEGER REFERENCES projects(id)")
    sample_columns = {row["name"] for row in sa.inspect(bind).get_columns("samples")}
    additions = {
        "category_id": "INTEGER REFERENCES dataset_categories(id)",
        "batch_id": "INTEGER REFERENCES dataset_batches(id)",
        "import_format": "VARCHAR(40)",
        "official_split": "VARCHAR(40)",
        "benchmark_label": "VARCHAR(40)",
        "benchmark_defect_type": "VARCHAR(160)",
        "mask_path": "VARCHAR(2000)",
    }
    for name, definition in additions.items():
        if name not in sample_columns:
            op.execute(sa.text(f"ALTER TABLE samples ADD COLUMN {name} {definition}"))
    for table, column in (("datasets", "project_id"), ("samples", "category_id"), ("samples", "batch_id")):
        op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})"))

    rows = bind.execute(sa.text("SELECT id, project FROM datasets WHERE project_id IS NULL AND project IS NOT NULL")).all()
    for dataset_id, legacy_name in rows:
        name = legacy_name.strip()
        if not name:
            continue
        project_id = bind.execute(sa.text("SELECT id FROM projects WHERE name=:name"), {"name": name}).scalar()
        if project_id is None:
            bind.execute(sa.text("INSERT INTO projects(name,created_at,updated_at) VALUES (:name,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"name": name})
            project_id = bind.execute(sa.text("SELECT id FROM projects WHERE name=:name"), {"name": name}).scalar_one()
        bind.execute(sa.text("UPDATE datasets SET project_id=:project_id WHERE id=:dataset_id"), {"project_id": project_id, "dataset_id": dataset_id})

    rows = bind.execute(sa.text("SELECT DISTINCT dataset_id,capture_batch_id FROM samples WHERE batch_id IS NULL AND capture_batch_id IS NOT NULL")).all()
    for dataset_id, code in rows:
        name = code.strip()
        if not name:
            continue
        batch_id = bind.execute(sa.text("SELECT id FROM dataset_batches WHERE dataset_id=:dataset_id AND code=:code"), {"dataset_id": dataset_id, "code": code}).scalar()
        if batch_id is None:
            bind.execute(sa.text("INSERT INTO dataset_batches(dataset_id,name,code) VALUES (:dataset_id,:name,:code)"), {"dataset_id": dataset_id, "name": name, "code": code})
            batch_id = bind.execute(sa.text("SELECT id FROM dataset_batches WHERE dataset_id=:dataset_id AND code=:code"), {"dataset_id": dataset_id, "code": code}).scalar_one()
        bind.execute(sa.text("UPDATE samples SET batch_id=:batch_id WHERE dataset_id=:dataset_id AND capture_batch_id=:code AND batch_id IS NULL"), {"batch_id": batch_id, "dataset_id": dataset_id, "code": code})


def downgrade() -> None:
    raise RuntimeError("Restore a verified metadata backup to downgrade.")
