from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "compare-transfer-quantization.py"
SPEC = importlib.util.spec_from_file_location("compare_transfer_quantization", MODULE_PATH)
assert SPEC and SPEC.loader
comparator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparator)


def write_manifest(path: pathlib.Path, **overrides):
    manifest = {
        "run_id": path.stem.removesuffix("-manifest"),
        "sequence_length": 32768,
        "model_identity": "hf:Qwen/Qwen2.5-0.5B-Instruct",
        "model_architecture": "Qwen2ForCausalLM",
        "dtype": "float32",
        "source_quantization": "none",
        "target_device": "cuda:g4dn.xlarge",
        "transfer_quantization": "none",
        "transfer_time_ms": 200.0,
        "total_time_ms": 300.0,
        "effective_bandwidth_gbps": 20.0,
        "transferred_bytes": 1024,
        "phase_status": "committed",
        "success": True,
        "error_message": None,
    }
    manifest.update(overrides)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def test_compares_paired_baseline_and_quantized_manifests():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        paths = [
            write_manifest(
                root / "migration-raw-a-manifest.json",
                transfer_time_ms=200.0,
                total_time_ms=400.0,
                fidelity_max_complete_exact_horizon=64,
            ),
            write_manifest(
                root / "migration-raw-b-manifest.json",
                transfer_time_ms=300.0,
                total_time_ms=500.0,
                fidelity_max_complete_exact_horizon=64,
            ),
            write_manifest(
                root / "migration-fp8-a-manifest.json",
                transfer_quantization="fp8",
                transfer_time_ms=50.0,
                total_time_ms=250.0,
                effective_bandwidth_gbps=80.0,
                transferred_bytes=256,
                fidelity_max_complete_exact_horizon=64,
            ),
        ]

        summary = comparator.build_comparison(paths, required_fidelity_horizon=32)

        assert summary["schema_version"] == "permeantos-transfer-quantization-comparison-v0"
        assert summary["manifest_count"] == 3
        group = summary["groups"][0]
        assert group["modes"]["none"]["median_transfer_time_ms"] == 250.0
        assert group["modes"]["fp8"]["median_transfer_time_ms"] == 50.0
        comparison = group["comparisons"][0]
        assert comparison["comparison_status"] == "comparable"
        assert comparison["fidelity_status"] == "verified"
        assert comparison["baseline_fidelity_status"] == "verified"
        assert comparison["candidate_fidelity_status"] == "verified"
        assert comparison["transfer_time_delta_ms"] == -200.0
        assert comparison["transfer_time_ratio"] == 0.2
        assert comparison["transfer_time_improvement_percent"] == 80.0
        assert comparison["transferred_bytes_ratio"] == 0.25


def test_marks_missing_baseline_as_insufficient_data():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        paths = [
            write_manifest(
                root / "migration-fp8-only-manifest.json",
                transfer_quantization="fp8",
                transfer_time_ms=50.0,
            )
        ]

        summary = comparator.build_comparison(paths)

        comparison = summary["groups"][0]["comparisons"][0]
        assert comparison == {
            "baseline_mode": "none",
            "candidate_mode": "fp8",
            "comparison_status": "insufficient_data",
            "reason": "missing_baseline_or_candidate_mode",
        }


def test_excludes_failed_runs_and_downgrades_unverified_fidelity():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        paths = [
            write_manifest(root / "migration-raw-manifest.json", transfer_time_ms=200.0),
            write_manifest(
                root / "migration-fp8-success-manifest.json",
                transfer_quantization="fp8",
                transfer_time_ms=80.0,
                total_time_ms=180.0,
            ),
            write_manifest(
                root / "migration-fp8-failed-manifest.json",
                transfer_quantization="fp8",
                transfer_time_ms=1.0,
                total_time_ms=1.0,
                phase_status="commit_failed",
                success=False,
                error_message="target rejected import",
            ),
        ]

        summary = comparator.build_comparison(paths, required_fidelity_horizon=64)

        group = summary["groups"][0]
        fp8 = group["modes"]["fp8"]
        assert fp8["success_count"] == 1
        assert fp8["failure_class_counts"] == {"commit_failed": 1}
        assert fp8["median_transfer_time_ms"] == 80.0
        comparison = group["comparisons"][0]
        assert comparison["comparison_status"] == "performance_only"
        assert comparison["fidelity_status"] == "unverified"
        assert comparison["baseline_fidelity_status"] == "unverified"
        assert comparison["candidate_fidelity_status"] == "unverified"


def test_requires_baseline_and_candidate_fidelity_evidence():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        paths = [
            write_manifest(root / "migration-raw-manifest.json", transfer_time_ms=200.0),
            write_manifest(
                root / "migration-fp8-manifest.json",
                transfer_quantization="fp8",
                transfer_time_ms=80.0,
                fidelity_max_complete_exact_horizon=64,
            ),
        ]

        summary = comparator.build_comparison(paths, required_fidelity_horizon=64)

        comparison = summary["groups"][0]["comparisons"][0]
        assert comparison["comparison_status"] == "performance_only"
        assert comparison["baseline_fidelity_status"] == "unverified"
        assert comparison["candidate_fidelity_status"] == "verified"


def test_directory_discovery_and_markdown_output():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        write_manifest(root / "migration-raw-manifest.json", transfer_time_ms=100.0)
        write_manifest(root / "migration-fp8-manifest.json", transfer_quantization="fp8", transfer_time_ms=25.0)
        (root / "ignored.json").write_text("{}\n")

        paths = comparator.discover_manifest_paths([root])
        summary = comparator.build_comparison(paths)
        markdown = comparator.markdown_table(summary)

        assert len(paths) == 2
        assert "Transfer improvement %" in markdown
        assert "| 32768 | fp8 | comparable | not_required | 100 | 25 | -75 | 75" in markdown
