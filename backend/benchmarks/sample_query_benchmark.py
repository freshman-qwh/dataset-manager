"""Measure the UX-D SQLite query paths without touching user datasets.

Example:
    python benchmarks/sample_query_benchmark.py --sample-count 10000 --annotations-per-sample 1
    python benchmarks/sample_query_benchmark.py --matrix
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import event, insert
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.annotation import Annotation
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.core.sqlite_runtime import (
    checkpoint_sqlite_wal,
    configure_sqlite_engine,
    initialize_sqlite_runtime,
    sqlite_runtime_snapshot,
)
from app.services import duplicate_service, sample_service, stats_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Dataset Manager SQLite query paths.")
    parser.add_argument("--sample-count", type=int, default=10_000)
    parser.add_argument("--annotations-per-sample", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Run the configured sample-count and annotation-density matrix.",
    )
    parser.add_argument("--sample-counts", default="10000,100000")
    parser.add_argument("--annotation-densities", default="1,10,100")
    parser.add_argument(
        "--max-annotation-rows",
        type=int,
        default=1_000_000,
        help="Skip matrix cases above this isolation safety cap; set 0 for no cap.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(math.ceil(len(ordered) * fraction) - 1, 0)
    return ordered[index]


class SelectCounter:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.count = 0

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._before_cursor_execute)
        return self

    def __exit__(self, *_args) -> None:
        event.remove(self.engine, "before_cursor_execute", self._before_cursor_execute)

    def _before_cursor_execute(
        self,
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            self.count += 1


def measure(engine, iterations: int, action: Callable[[], object]) -> dict[str, float | int]:
    durations: list[float] = []
    select_counts: list[int] = []
    response_bytes = 0
    peak_bytes = 0
    for _ in range(iterations):
        tracemalloc.start()
        started = time.perf_counter()
        with SelectCounter(engine) as counter:
            result = action()
        durations.append((time.perf_counter() - started) * 1000)
        _, current_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_bytes = max(peak_bytes, current_peak)
        select_counts.append(counter.count)
        if hasattr(result, "model_dump_json"):
            response_bytes = len(result.model_dump_json().encode("utf-8"))
    return {
        "p50_ms": round(percentile(durations, 0.50), 2),
        "p95_ms": round(percentile(durations, 0.95), 2),
        "select_count_max": max(select_counts),
        "response_bytes": response_bytes,
        "peak_memory_bytes": peak_bytes,
    }


def seed_database(session: Session, sample_count: int, annotations_per_sample: int) -> int:
    dataset = Dataset(name="UX-D isolated benchmark")
    session.add(dataset)
    session.flush()
    assert dataset.id is not None
    dataset_id = dataset.id
    sample_rows = []
    for index in range(sample_count):
        sample_rows.append(
            {
                "dataset_id": dataset_id,
                "filename": f"image-{index:07d}.png",
                "absolute_path": f"/isolated-benchmark/image-{index:07d}.png",
                "relative_path": f"images/{index // 1000:04d}/image-{index:07d}.png",
                "file_size": 1_024 + (index % 2_048),
                "extension": ".png",
                "file_type": "image",
                "mime_type": "image/png",
                "file_hash": f"hash-{index // 2}" if index < 200 else f"hash-{index}",
                "file_status": "normal",
                "split": ("train", "val", "test", None)[index % 4],
                "annotation_progress": (
                    "not_started",
                    "in_progress",
                    "completed_empty",
                    "completed_with_objects",
                )[index % 4],
                "review_status": ("not_reviewed", "in_review", "approved", "rejected")[index % 4],
            }
        )
    for start in range(0, len(sample_rows), 5_000):
        session.exec(insert(Sample), params=sample_rows[start:start + 5_000])
    session.commit()

    if annotations_per_sample > 0:
        sample_ids = list(
            session.exec(
                select(Sample.id)
                .where(Sample.dataset_id == dataset_id)
                .order_by(Sample.id)
            ).all()
        )
        annotation_rows = []
        for sample_id in sample_ids:
            for annotation_index in range(annotations_per_sample):
                annotation_rows.append(
                    {
                        "sample_id": int(sample_id),
                        "dataset_id": dataset_id,
                        "label": f"class-{annotation_index % 20}",
                        "shape_type": "rectangle",
                        "points_json": "[[0, 0], [10, 10]]",
                    }
                )
                if len(annotation_rows) == 10_000:
                    session.exec(insert(Annotation), params=annotation_rows)
                    session.commit()
                    annotation_rows.clear()
        if annotation_rows:
            session.exec(insert(Annotation), params=annotation_rows)
            session.commit()
    return dataset_id


def run_benchmark(
    sample_count: int,
    annotations_per_sample: int,
    iterations: int,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="dataset-manager-uxd-") as temp_dir:
        database_path = Path(temp_dir) / "benchmark.sqlite3"
        engine = configure_sqlite_engine(
            create_engine(
                f"sqlite:///{database_path}",
                connect_args={"check_same_thread": False},
            )
        )
        try:
            initialize_sqlite_runtime(engine)
            SQLModel.metadata.create_all(engine)
            seed_started = time.perf_counter()
            with Session(engine) as session:
                dataset_id = seed_database(
                    session,
                    sample_count,
                    annotations_per_sample,
                )
                seed_ms = round((time.perf_counter() - seed_started) * 1000, 2)
                middle_id = session.exec(
                    select(Sample.id)
                    .where(Sample.dataset_id == dataset_id)
                    .order_by(Sample.id)
                    .offset(sample_count // 2)
                    .limit(1)
                ).one()
                results = {
                    "status": "completed",
                    "sample_count": sample_count,
                    "annotations_per_sample": annotations_per_sample,
                    "annotation_rows": sample_count * annotations_per_sample,
                    "iterations": iterations,
                    "seed_ms": seed_ms,
                    "sample_list": measure(
                        engine,
                        iterations,
                        lambda: sample_service.list_samples(
                            session,
                            dataset_id,
                            search="image-00",
                            file_type="image",
                            page=3,
                            page_size=60,
                            sort_by="filename",
                            sort_order="asc",
                        ),
                    ),
                    "sample_navigation": measure(
                        engine,
                        iterations,
                        lambda: sample_service.get_sample_navigation(
                            session,
                            dataset_id,
                            sample_id=int(middle_id),
                            queue_scope="current_filter",
                            sort_by="filename",
                            sort_order="asc",
                        ),
                    ),
                    "stats": measure(
                        engine,
                        iterations,
                        lambda: stats_service.get_dataset_stats(session, dataset_id),
                    ),
                    "duplicates": measure(
                        engine,
                        iterations,
                        lambda: duplicate_service.get_duplicate_report(session, dataset_id),
                    ),
                }
            results["sqlite_before_checkpoint"] = sqlite_runtime_snapshot(
                engine,
                database_path,
            )
            results["checkpoint"] = checkpoint_sqlite_wal(engine)
            results["sqlite_after_checkpoint"] = sqlite_runtime_snapshot(
                engine,
                database_path,
            )
        finally:
            engine.dispose()
    return results


def _parse_positive_csv(value: str, name: str, *, allow_zero: bool = False) -> list[int]:
    try:
        parsed = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise SystemExit(f"{name} must be a comma-separated integer list.") from exc
    minimum = 0 if allow_zero else 1
    if not parsed or any(item < minimum for item in parsed):
        qualifier = "non-negative" if allow_zero else "positive"
        raise SystemExit(f"{name} must contain {qualifier} integers.")
    return parsed


def main() -> None:
    args = parse_args()
    if args.sample_count < 1 or args.annotations_per_sample < 0 or args.iterations < 1:
        raise SystemExit(
            "sample-count and iterations must be positive; "
            "annotations-per-sample cannot be negative."
        )

    if args.matrix:
        sample_counts = _parse_positive_csv(args.sample_counts, "sample-counts")
        annotation_densities = _parse_positive_csv(
            args.annotation_densities,
            "annotation-densities",
            allow_zero=True,
        )
        cases: list[dict[str, object]] = []
        for sample_count in sample_counts:
            for density in annotation_densities:
                annotation_rows = sample_count * density
                if (
                    args.max_annotation_rows > 0
                    and annotation_rows > args.max_annotation_rows
                ):
                    cases.append(
                        {
                            "status": "skipped",
                            "sample_count": sample_count,
                            "annotations_per_sample": density,
                            "annotation_rows": annotation_rows,
                            "reason": (
                                "annotation row count exceeds isolation safety cap "
                                f"{args.max_annotation_rows}"
                            ),
                        }
                    )
                    continue
                cases.append(run_benchmark(sample_count, density, args.iterations))
        results: dict[str, object] = {
            "mode": "matrix",
            "iterations": args.iterations,
            "max_annotation_rows": args.max_annotation_rows,
            "cases": cases,
        }
    else:
        results = run_benchmark(
            args.sample_count,
            args.annotations_per_sample,
            args.iterations,
        )

    output = json.dumps(results, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{output}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
