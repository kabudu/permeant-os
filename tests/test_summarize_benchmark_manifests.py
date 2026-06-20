from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "summarize-benchmark-manifests.py"
SPEC = importlib.util.spec_from_file_location("summarize_benchmark_manifests", MODULE_PATH)
assert SPEC and SPEC.loader
summarizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summarizer)


def write_manifest(path: pathlib.Path, **overrides):
    manifest = {
        "run_id": path.stem.removesuffix("-manifest"),
        "sequence_length": 2016,
        "transfer_quantization": "none",
        "transfer_time_ms": 100.0,
        "total_time_ms": 150.0,
        "effective_bandwidth_gbps": 1.5,
        "chunks_sent": 64,
        "phase_status": "committed",
        "success": True,
        "error_message": None,
    }
    manifest.update(overrides)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def test_summarizes_manifest_groups_and_paper_rows():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        paths = [
            write_manifest(root / "migration-a-manifest.json", transfer_time_ms=100.0, total_time_ms=200.0),
            write_manifest(root / "migration-b-manifest.json", transfer_time_ms=300.0, total_time_ms=400.0),
            write_manifest(
                root / "migration-c-manifest.json",
                sequence_length=32768,
                transfer_quantization="fp8",
                transfer_time_ms=50.0,
                total_time_ms=70.0,
                effective_bandwidth_gbps=25.0,
            ),
        ]

        summary = summarizer.summarize_manifests(paths)

        assert summary["schema_version"] == "permeantos-benchmark-summary-v0"
        assert summary["manifest_count"] == 3
        assert summary["success_count"] == 3
        assert summary["failure_count"] == 0
        assert len(summary["groups"]) == 2
        none_group = next(group for group in summary["groups"] if group["transfer_quantization"] == "none")
        assert none_group["run_count"] == 2
        assert none_group["transfer_time_ms"]["median"] == 200.0
        assert none_group["total_time_ms"]["median"] == 300.0
        assert summary["paper_table_rows"][0]["runs"] >= 1


def test_records_failure_classes_without_polluting_success_medians():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        success = write_manifest(root / "migration-success-manifest.json", transfer_time_ms=100.0)
        failure = write_manifest(
            root / "migration-failed-manifest.json",
            phase_status="graph_binding_failed",
            success=False,
            transfer_time_ms=9999.0,
            total_time_ms=9999.0,
            error_message="agent_graph.kv_spans[0] exceeds target context window",
        )

        summary = summarizer.summarize_manifests([success, failure])

        assert summary["success_count"] == 1
        assert summary["failure_count"] == 1
        assert summary["failure_records"] == [
            {
                "run_id": "migration-failed",
                "source_path": str(failure),
                "phase_status": "graph_binding_failed",
                "failure_class": "graph_binding_failed",
                "error_message": "agent_graph.kv_spans[0] exceeds target context window",
            }
        ]
        group = summary["groups"][0]
        assert group["failure_class_counts"] == {"graph_binding_failed": 1}
        assert group["transfer_time_ms"]["median"] == 100.0


def test_legacy_success_without_phase_status_counts_as_success():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        manifest = write_manifest(root / "migration-legacy-manifest.json")
        data = json.loads(manifest.read_text())
        data.pop("phase_status")
        manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

        summary = summarizer.summarize_manifests([manifest])

        assert summary["success_count"] == 1
        assert summary["failure_count"] == 0
        assert summary["failure_records"] == []


def test_boolean_numeric_fields_are_ignored():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        manifest = write_manifest(
            root / "migration-bool-manifest.json",
            transfer_time_ms=True,
            total_time_ms=False,
        )

        summary = summarizer.summarize_manifests([manifest])

        group = summary["groups"][0]
        assert group["transfer_time_ms"]["median"] is None
        assert group["total_time_ms"]["median"] is None


def test_discovers_directory_manifests_and_writes_markdown_table():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        write_manifest(root / "migration-a-manifest.json")
        ignored = root / "not-a-manifest.json"
        ignored.write_text("{}\n")

        paths = summarizer.discover_manifest_paths([root])
        summary = summarizer.summarize_manifests(paths)
        markdown = summarizer.markdown_table(summary)

        assert paths == [(root / "migration-a-manifest.json").resolve()]
        assert "Median transfer ms" in markdown
        assert "| 2016 | none | 1 | 1 | 100.0 | 150.0 | 1.5 |" in markdown
