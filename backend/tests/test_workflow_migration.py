from sqlalchemy import create_engine, text

from app.core import database


def test_workflow_semantics_backfill_preserves_independent_states(tmp_path, monkeypatch):
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(database, "engine", migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(text("CREATE TABLE datasets (id INTEGER PRIMARY KEY, task_type VARCHAR(80))"))
        connection.execute(
            text(
                "CREATE TABLE samples ("
                "id INTEGER PRIMARY KEY, review_status VARCHAR(40), "
                "annotation_progress VARCHAR(40) DEFAULT 'not_started')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE annotation_classes ("
                "id INTEGER PRIMARY KEY, dataset_id INTEGER, name VARCHAR(120), "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE annotations ("
                "id INTEGER PRIMARY KEY, sample_id INTEGER, dataset_id INTEGER, "
                "label VARCHAR(120), class_id INTEGER)"
            )
        )
        connection.execute(text("INSERT INTO datasets (id, task_type) VALUES (1, NULL)"))
        connection.execute(
            text(
                "INSERT INTO samples (id, review_status, annotation_progress) VALUES "
                "(1, 'unlabeled', 'not_started'), "
                "(2, 'approved', 'completed_empty')"
            )
        )
        connection.execute(
            text("INSERT INTO annotations (id, sample_id, dataset_id, label) VALUES (1, 1, 1, 'defect')")
        )

    database._backfill_workflow_semantics()

    with migration_engine.connect() as connection:
        assert connection.execute(text("SELECT task_type FROM datasets WHERE id = 1")).scalar_one() == "detection"
        rows = connection.execute(
            text("SELECT id, review_status, annotation_progress FROM samples ORDER BY id")
        ).all()
        classes = connection.execute(text("SELECT dataset_id, name FROM annotation_classes")).all()
        annotation_class_id = connection.execute(text("SELECT class_id FROM annotations WHERE id = 1")).scalar_one()
    assert rows == [
        (1, "not_reviewed", "in_progress"),
        (2, "approved", "completed_empty"),
    ]
    assert classes == [(1, "defect")]
    assert annotation_class_id is not None
