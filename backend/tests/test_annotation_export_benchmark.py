from benchmarks.annotation_export_benchmark import run_benchmark


def test_voc_export_benchmark_keeps_result_and_memory_bounded() -> None:
    result = run_benchmark(
        sample_count=250,
        objects_per_sample=1,
        max_peak_memory_mb=16,
    )

    assert result["status"] == "completed"
    assert result["artifact_entry_count"] == 251
    assert result["parameter_snapshot_bytes"] < 1024
    assert result["result_summary_bytes"] < 4096
    assert result["checkpoint_count"] >= 11
    assert result["progress_update_count"] == 10
