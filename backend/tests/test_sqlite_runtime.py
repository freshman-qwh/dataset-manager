import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from app.core.sqlite_runtime import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_WAL_AUTOCHECKPOINT_PAGES,
    checkpoint_sqlite_wal,
    configure_sqlite_engine,
    initialize_sqlite_runtime,
    sqlite_runtime_snapshot,
)
from app.models.annotation import Annotation
from app.models.annotation_class import AnnotationClass
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.models.tag import Tag
from app.services import dataset_service, tag_service


def _make_engine(tmp_path):
    database_path = tmp_path / "runtime.sqlite3"
    engine = configure_sqlite_engine(
        create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
    )
    initialize_sqlite_runtime(engine)
    return engine, database_path


def test_sqlite_runtime_enables_wal_timeout_foreign_keys_and_checkpoint(tmp_path):
    engine, database_path = _make_engine(tmp_path)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE parents (id INTEGER PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE children ("
                "id INTEGER PRIMARY KEY, "
                "parent_id INTEGER NOT NULL REFERENCES parents(id)"
                ")"
            )

        snapshot = sqlite_runtime_snapshot(engine, database_path)
        assert snapshot["journal_mode"] == "wal"
        assert snapshot["foreign_keys"] is True
        assert snapshot["busy_timeout_ms"] == SQLITE_BUSY_TIMEOUT_MS
        assert (
            snapshot["wal_autocheckpoint_pages"]
            == SQLITE_WAL_AUTOCHECKPOINT_PAGES
        )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO children (parent_id) VALUES (999)"
                )

        checkpoint = checkpoint_sqlite_wal(engine)
        assert checkpoint["mode"] == "passive"
        assert checkpoint["busy"] == 0
        assert checkpoint["checkpointed_pages"] <= checkpoint["log_pages"]
    finally:
        engine.dispose()


def test_sqlite_busy_timeout_waits_for_a_short_writer_transaction(tmp_path):
    engine, _database_path = _make_engine(tmp_path)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )

        def contender() -> float:
            started = time.perf_counter()
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO events (value) VALUES ('contender')"
                )
            return (time.perf_counter() - started) * 1000

        with engine.connect() as holder:
            holder.exec_driver_sql("BEGIN IMMEDIATE")
            holder.exec_driver_sql(
                "INSERT INTO events (value) VALUES ('holder')"
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(contender)
                time.sleep(0.1)
                holder.commit()
                wait_ms = future.result(timeout=2)

        assert wait_ms >= 75
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM events"
                ).scalar_one()
                == 2
            )
    finally:
        engine.dispose()


def test_foreign_key_mode_keeps_metadata_deletes_consistent(tmp_path):
    engine, _database_path = _make_engine(tmp_path)
    try:
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            dataset = Dataset(name="foreign-key-delete")
            session.add(dataset)
            session.flush()
            assert dataset.id is not None
            annotation_class = AnnotationClass(
                dataset_id=dataset.id,
                name="object",
            )
            tag = Tag(dataset_id=dataset.id, name="legacy-tag")
            session.add(annotation_class)
            session.add(tag)
            session.flush()
            sample = Sample(
                dataset_id=dataset.id,
                filename="sample.png",
                absolute_path="/isolated/sample.png",
                relative_path="sample.png",
                extension=".png",
                file_type="image",
                file_hash="hash",
            )
            sample.tags.append(tag)
            session.add(sample)
            session.flush()
            assert sample.id is not None
            assert annotation_class.id is not None
            assert tag.id is not None
            annotation = Annotation(
                dataset_id=dataset.id,
                sample_id=sample.id,
                class_id=annotation_class.id,
                tag_id=tag.id,
                label="object",
                shape_type="rectangle",
                points_json="[[0, 0], [10, 10]]",
            )
            session.add(annotation)
            session.commit()
            annotation_id = annotation.id
            dataset_id = dataset.id
            tag_id = tag.id
            class_id = annotation_class.id

            tag_service.delete_tag(session, tag_id)
            session.expire_all()
            assert session.get(Annotation, annotation_id).tag_id is None

            dataset_service.delete_dataset(session, dataset_id)
            assert session.get(Dataset, dataset_id) is None
            assert session.get(AnnotationClass, class_id) is None
    finally:
        engine.dispose()
