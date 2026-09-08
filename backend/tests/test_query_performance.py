from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.dataset import Dataset
from app.models.sample import Sample
from app.services import duplicate_service, sample_service, stats_service


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_samples(session: Session, count: int) -> int:
    dataset = Dataset(name=f"query-scale-{count}")
    session.add(dataset)
    session.flush()
    assert dataset.id is not None
    session.add_all(
        [
            Sample(
                dataset_id=dataset.id,
                filename=f"image-{index:05d}.png",
                absolute_path=f"/benchmark/image-{index:05d}.png",
                relative_path=f"images/image-{index:05d}.png",
                file_size=1024 + index,
                extension=".png",
                file_type="image",
                mime_type="image/png",
                file_hash=f"hash-{index // 2}" if index < 20 else f"hash-{index}",
                split=("train", "val", None)[index % 3],
                annotation_progress=(
                    "not_started",
                    "in_progress",
                    "completed_empty",
                    "completed_with_objects",
                )[index % 4],
                review_status=("not_reviewed", "in_review", "approved")[index % 3],
            )
            for index in range(count)
        ]
    )
    session.commit()
    return dataset.id


def _count_selects(engine, action) -> int:
    statements = 0

    def before_cursor_execute(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal statements
        if statement.lstrip().upper().startswith("SELECT"):
            statements += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return statements


def test_sample_list_and_navigation_query_counts_do_not_scale_with_dataset_size():
    engine = _make_engine()
    with Session(engine) as session:
        dataset_id = _seed_samples(session, 1_000)

        def list_action():
            result = sample_service.list_samples(
                session,
                dataset_id,
                search="image-000",
                file_type="image",
                page=2,
                page_size=25,
                sort_by="filename",
                sort_order="asc",
            )
            assert result.total == 100
            assert len(result.items) == 25

        list_selects = _count_selects(engine, list_action)
        assert list_selects <= 3

        target = session.exec(
            sample_service._apply_sample_filters(  # noqa: SLF001 - focused query regression
                select(Sample.id),
                session,
                dataset_id,
                search="image-000",
                file_type="image",
            ).order_by(Sample.filename)
        ).all()[50]

        def navigation_action():
            result = sample_service.get_sample_navigation(
                session,
                dataset_id,
                sample_id=int(target),
                search="image-000",
                queue_scope="current_filter",
                sort_by="filename",
                sort_order="asc",
            )
            assert result.total == 100
            assert result.current_index == 50
            assert result.previous_sample is not None
            assert result.next_sample is not None

        navigation_selects = _count_selects(engine, navigation_action)
        assert navigation_selects <= 7

        null_split_id = session.exec(
            select(Sample.id)
            .where(
                Sample.dataset_id == dataset_id,
                Sample.split.is_(None),
            )
            .order_by(Sample.id)
            .limit(1)
        ).one()
        null_split_navigation = sample_service.get_sample_navigation(
            session,
            dataset_id,
            sample_id=int(null_split_id),
            queue_scope="current_filter",
            sort_by="split",
            sort_order="asc",
        )
        assert null_split_navigation.current_sample is not None
        assert null_split_navigation.current_sample.split is None
        assert null_split_navigation.current_index == 0
        assert null_split_navigation.previous_sample is None
        assert null_split_navigation.next_sample is not None


def test_sample_list_returns_bounded_adjacent_thumbnail_prefetch_ids():
    engine = _make_engine()
    with Session(engine) as session:
        dataset_id = _seed_samples(session, 40)
        result = sample_service.list_samples(
            session,
            dataset_id,
            page=2,
            page_size=10,
            sort_by="filename",
            sort_order="asc",
            thumbnail_prefetch=3,
        )
        current_ids = {sample.id for sample in result.items}
        assert len(result.thumbnail_prefetch_sample_ids) == 6
        assert not current_ids.intersection(result.thumbnail_prefetch_sample_ids)
        assert result.thumbnail_prefetch_sample_ids == [8, 9, 10, 21, 22, 23]

        without_prefetch = sample_service.list_samples(
            session,
            dataset_id,
            page=2,
            page_size=10,
        )
        assert without_prefetch.thumbnail_prefetch_sample_ids == []
    engine.dispose()


def test_stats_and_duplicate_report_only_materialize_aggregate_or_duplicate_rows():
    engine = _make_engine()
    with Session(engine) as session:
        dataset_id = _seed_samples(session, 1_000)

        stats_selects = _count_selects(
            engine,
            lambda: stats_service.get_dataset_stats(session, dataset_id),
        )
        duplicate_result = None

        def duplicate_action():
            nonlocal duplicate_result
            duplicate_result = duplicate_service.get_duplicate_report(
                session,
                dataset_id,
                page=1,
                page_size=3,
            )

        duplicate_selects = _count_selects(engine, duplicate_action)

        assert stats_selects <= 13
        assert duplicate_selects <= 3
        assert duplicate_result is not None
        assert duplicate_result.group_count == 10
        assert duplicate_result.duplicate_sample_count == 20
        assert duplicate_result.filtered_group_count == 10
        assert len(duplicate_result.groups) == 3
        assert duplicate_result.has_next is True


def test_duplicate_report_bounds_samples_inside_a_large_group():
    engine = _make_engine()
    with Session(engine) as session:
        dataset_id = _seed_samples(session, 1)
        session.add_all(
            [
                Sample(
                    dataset_id=dataset_id,
                    filename=f"copy-{index:03d}.png",
                    absolute_path=f"/benchmark/copy-{index:03d}.png",
                    relative_path=f"copies/copy-{index:03d}.png",
                    file_size=1024,
                    extension=".png",
                    file_type="image",
                    mime_type="image/png",
                    file_hash="large-duplicate-group",
                    split="train" if index % 2 == 0 else "val",
                )
                for index in range(25)
            ]
        )
        session.commit()

        report = duplicate_service.get_duplicate_report(session, dataset_id)

        assert report.group_count == 1
        assert report.groups[0].count == 25
        assert len(report.groups[0].samples) == 20
        assert report.groups[0].samples_truncated is True
        assert report.groups[0].cross_split is True
        assert report.groups[0].training_splits == ["train", "val"]
        assert report.groups[0].split_counts == {"train": 13, "val": 12}
        assert sum(report.groups[0].split_counts.values()) == report.groups[0].count
    engine.dispose()
