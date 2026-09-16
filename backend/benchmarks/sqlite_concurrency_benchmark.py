"""Measure the isolated SQLite WAL and lock-wait baseline.

The benchmark creates a temporary database, uses one short-transaction writer,
keeps several readers active, and then verifies that a second writer waits for
an intentional lock instead of failing immediately.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine

from app.core.sqlite_runtime import (
    checkpoint_sqlite_wal,
    configure_sqlite_engine,
    initialize_sqlite_runtime,
    sqlite_runtime_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Dataset Manager's isolated SQLite concurrency baseline."
    )
    parser.add_argument("--writes", type=int, default=300)
    parser.add_argument("--readers", type=int, default=4)
    parser.add_argument("--lock-hold-ms", type=int, default=150)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(math.ceil(len(ordered) * fraction) - 1, 0)
    return ordered[index]


def _is_locked_error(error: BaseException) -> bool:
    return isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower()


def run_concurrent_workload(
    engine,
    database_path: Path,
    writes: int,
    readers: int,
) -> dict[str, object]:
    start_event = threading.Event()
    writer_done = threading.Event()
    writer_latencies: list[float] = []
    reader_latencies: list[float] = []
    locked_errors: list[str] = []
    successful_writes = 0
    successful_reads = 0
    max_wal_bytes = 0
    metrics_lock = threading.Lock()
    wal_path = Path(f"{database_path}-wal")

    def writer() -> None:
        nonlocal max_wal_bytes, successful_writes
        start_event.wait()
        try:
            for index in range(writes):
                started = time.perf_counter()
                try:
                    with engine.begin() as connection:
                        connection.exec_driver_sql(
                            "INSERT INTO events (value) VALUES (?)",
                            (f"write-{index}",),
                        )
                    writer_latencies.append(
                        (time.perf_counter() - started) * 1000
                    )
                    successful_writes += 1
                except BaseException as exc:
                    if _is_locked_error(exc):
                        with metrics_lock:
                            locked_errors.append(str(exc))
                    else:
                        raise
                if index % 10 == 0 and wal_path.exists():
                    max_wal_bytes = max(max_wal_bytes, wal_path.stat().st_size)
        finally:
            writer_done.set()

    def reader() -> None:
        nonlocal successful_reads
        start_event.wait()
        while not writer_done.is_set():
            started = time.perf_counter()
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql(
                        "SELECT COUNT(*) FROM events"
                    ).scalar_one()
                reader_latencies.append(
                    (time.perf_counter() - started) * 1000
                )
                with metrics_lock:
                    successful_reads += 1
            except BaseException as exc:
                if _is_locked_error(exc):
                    with metrics_lock:
                        locked_errors.append(str(exc))
                else:
                    raise

    with ThreadPoolExecutor(max_workers=readers + 1) as executor:
        futures = [executor.submit(writer)]
        futures.extend(executor.submit(reader) for _ in range(readers))
        start_event.set()
        for future in futures:
            future.result()
    if wal_path.exists():
        max_wal_bytes = max(max_wal_bytes, wal_path.stat().st_size)

    return {
        "requested_writes": writes,
        "successful_writes": successful_writes,
        "reader_workers": readers,
        "reader_queries": successful_reads,
        "locked_errors": len(locked_errors),
        "writer_p50_ms": round(percentile(writer_latencies, 0.50), 2),
        "writer_p95_ms": round(percentile(writer_latencies, 0.95), 2),
        "reader_p50_ms": round(percentile(reader_latencies, 0.50), 2),
        "reader_p95_ms": round(percentile(reader_latencies, 0.95), 2),
        "max_wal_bytes": max_wal_bytes,
    }


def measure_lock_wait(engine, lock_hold_ms: int) -> dict[str, object]:
    contender_result: dict[str, object] = {}

    def contender() -> None:
        started = time.perf_counter()
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO events (value) VALUES ('lock-contender')"
                )
            contender_result["succeeded"] = True
        except BaseException as exc:
            contender_result["succeeded"] = False
            contender_result["error"] = str(exc)
            contender_result["locked_error"] = _is_locked_error(exc)
        contender_result["wait_ms"] = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

    with engine.connect() as holder:
        holder.exec_driver_sql("BEGIN IMMEDIATE")
        holder.exec_driver_sql(
            "INSERT INTO events (value) VALUES ('lock-holder')"
        )
        thread = threading.Thread(target=contender)
        thread.start()
        time.sleep(lock_hold_ms / 1000)
        holder.commit()
        thread.join()

    return {
        "lock_hold_ms": lock_hold_ms,
        **contender_result,
    }


def main() -> None:
    args = parse_args()
    if args.writes < 1 or args.readers < 1 or args.lock_hold_ms < 1:
        raise SystemExit("writes, readers, and lock-hold-ms must be positive.")

    with tempfile.TemporaryDirectory(prefix="dataset-manager-sqlite-") as temp_dir:
        database_path = Path(temp_dir) / "concurrency.sqlite3"
        engine = configure_sqlite_engine(
            create_engine(
                f"sqlite:///{database_path}",
                connect_args={"check_same_thread": False},
            )
        )
        try:
            initialize_sqlite_runtime(engine)
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO events (value) VALUES ('seed')"
                )
            workload = run_concurrent_workload(
                engine,
                database_path,
                args.writes,
                args.readers,
            )
            lock_wait = measure_lock_wait(engine, args.lock_hold_ms)
            before_checkpoint = sqlite_runtime_snapshot(engine, database_path)
            checkpoint = checkpoint_sqlite_wal(engine)
            after_checkpoint = sqlite_runtime_snapshot(engine, database_path)
            results = {
                "workload": workload,
                "lock_wait": lock_wait,
                "sqlite_before_checkpoint": before_checkpoint,
                "checkpoint": checkpoint,
                "sqlite_after_checkpoint": after_checkpoint,
            }
        finally:
            engine.dispose()

    output = json.dumps(results, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{output}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
