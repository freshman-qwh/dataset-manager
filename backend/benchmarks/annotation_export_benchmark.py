"""Measure bounded Pascal VOC archive writing without touching user datasets.

Example:
    python benchmarks/annotation_export_benchmark.py --sample-count 100000
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import time
import tracemalloc
from zipfile import ZipFile

from app.models.sample import Sample
from app.schemas.annotation import AnnotationRead
from app.services import annotation_export_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark bounded Pascal VOC task artifact writing."
    )
    parser.add_argument("--sample-count", type=int, default=100_000)
    parser.add_argument("--objects-per-sample", type=int, default=1)
    parser.add_argument("--max-peak-memory-mb", type=float, default=128.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _synthetic_export_samples(sample_count: int, objects_per_sample: int):
    now = datetime.now(UTC)
    for index in range(sample_count):
        sample_id = index + 1
        relative_path = f"images/{index // 1_000:04d}/image-{index:07d}.png"
        sample = Sample(
            id=sample_id,
            dataset_id=1,
            filename=f"image-{index:07d}.png",
            absolute_path=f"/isolated-export/{relative_path}",
            relative_path=relative_path,
            file_size=1_024,
            extension=".png",
            file_type="image",
            mime_type="image/png",
            file_hash=f"hash-{index:07d}",
            file_status="normal",
            split=("train", "val", "test", None)[index % 4],
        )
        annotations = [
            AnnotationRead(
                id=index * objects_per_sample + object_index + 1,
                sample_id=sample_id,
                dataset_id=1,
                label=f"class-{object_index % 20}",
                shape_type="rectangle",
                points=[1.0, 2.0, 20.0, 22.0],
                attributes={
                    "occluded": object_index % 2 == 0,
                    "truncated": False,
                    "difficult": False,
                },
                created_at=now,
                updated_at=now,
            )
            for object_index in range(objects_per_sample)
        ]
        yield annotation_export_service._ExportSample(
            sample=sample,
            annotations=annotations,
            image_width=64,
            image_height=48,
        )


def run_benchmark(
    sample_count: int,
    objects_per_sample: int,
    max_peak_memory_mb: float,
) -> dict[str, object]:
    if sample_count <= 0:
        raise ValueError("sample_count must be positive.")
    if objects_per_sample < 0:
        raise ValueError("objects_per_sample cannot be negative.")

    report = {
        "dataset_id": 1,
        "dataset_name": "F2-3D3 isolated export benchmark",
        "format": "voc",
        "sample_count": sample_count,
        "exported_sample_count": sample_count,
        "exported_object_count": sample_count * objects_per_sample,
        "raw_images_included": False,
        "issues": [],
    }
    parameter_snapshot = {
        "format": "voc",
        "sample_query": {"sort_by": "relative_path", "sort_order": "asc"},
        "include_empty": objects_per_sample == 0,
    }
    checkpoints = 0
    progress_updates = 0

    def checkpoint() -> None:
        nonlocal checkpoints
        checkpoints += 1

    def progress(_current: int, _total: int) -> None:
        nonlocal progress_updates
        progress_updates += 1

    with tempfile.TemporaryDirectory(prefix="dataset-manager-export-") as temp_dir:
        destination = Path(temp_dir) / "pascal-voc.zip"
        tracemalloc.start()
        started = time.perf_counter()
        annotation_export_service._write_voc_zip(
            "F2-3D3 isolated export benchmark",
            _synthetic_export_samples(sample_count, objects_per_sample),
            report,
            destination,
            total=sample_count,
            checkpoint=checkpoint,
            progress=progress,
        )
        duration_ms = round((time.perf_counter() - started) * 1_000, 2)
        _, peak_memory_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        artifact_size_bytes = destination.stat().st_size
        with ZipFile(destination) as archive:
            entry_count = len(archive.infolist())

    max_peak_memory_bytes = int(max_peak_memory_mb * 1024 * 1024)
    return {
        "status": "completed" if peak_memory_bytes <= max_peak_memory_bytes else "memory_limit_exceeded",
        "sample_count": sample_count,
        "objects_per_sample": objects_per_sample,
        "artifact_entry_count": entry_count,
        "artifact_size_bytes": artifact_size_bytes,
        "duration_ms": duration_ms,
        "peak_memory_bytes": peak_memory_bytes,
        "max_peak_memory_bytes": max_peak_memory_bytes,
        "parameter_snapshot_bytes": len(
            json.dumps(parameter_snapshot, sort_keys=True).encode("utf-8")
        ),
        "result_summary_bytes": len(json.dumps(report, sort_keys=True).encode("utf-8")),
        "checkpoint_count": checkpoints,
        "progress_update_count": progress_updates,
    }


def main() -> int:
    args = parse_args()
    result = run_benchmark(
        args.sample_count,
        args.objects_per_sample,
        args.max_peak_memory_mb,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
