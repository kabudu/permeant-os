from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "aws-real-runtime-e2e.sh"


def run_preflight(temp_dir: pathlib.Path, **overrides):
    env = os.environ.copy()
    env.update(
        {
            "PERMEANT_STATE_DIR": str(temp_dir / "state"),
            "PERMEANT_PREFLIGHT_SKIP_AWS": "1",
            "PERMEANT_PREFLIGHT_SKIP_BUILD": "1",
            "PERMEANT_PREFLIGHT_SKIP_SOURCE": "1",
            "PERMEANT_SEQ_LEN": "2016",
            "PERMEANT_VLLM_MAX_MODEL_LEN": "2048",
            "PERMEANT_TRANSFER_QUANTIZATION": "none",
        }
    )
    env.update(overrides)
    return subprocess.run(
        [str(RUNNER), "preflight"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def latest_report(temp_dir: pathlib.Path) -> dict:
    latest = temp_dir / "state" / "latest"
    state = json.loads((latest / "state.json").read_text())
    report = json.loads(pathlib.Path(state["preflight_report"]).read_text())
    return report


def test_preflight_passes_with_explicit_ci_skips():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(temp_dir)

        assert result.returncode == 0, result.stderr + result.stdout
        report = latest_report(temp_dir)
        assert report["schema_version"] == "permeantos-aws-e2e-preflight-v0"
        assert report["ok"] is True
        assert report["failed_count"] == 0
        assert report["skipped_count"] >= 3
        names = {check["name"]: check["status"] for check in report["checks"]}
        assert names["configuration:transfer_quantization"] == "pass"
        assert names["configuration:validation_profile"] == "pass"
        assert names["aws:identity"] == "skip"
        assert names["local:permeant_cli"] == "skip"
        assert names["source:continuation_file"] == "skip"
        assert names["source:agent_graph_manifest"] == "skip"


def test_preflight_passes_for_qatq_transfer_quantization():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(temp_dir, PERMEANT_TRANSFER_QUANTIZATION="qatq")

        assert result.returncode == 0, result.stderr + result.stdout
        report = latest_report(temp_dir)
        checks = {check["name"]: check for check in report["checks"]}
        assert report["ok"] is True
        assert checks["configuration:transfer_quantization"]["status"] == "pass"
        assert "qatq is supported" in checks["configuration:transfer_quantization"]["message"]


def test_preflight_fails_for_unsupported_transfer_quantization():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(temp_dir, PERMEANT_TRANSFER_QUANTIZATION="turboquant")

        assert result.returncode == 1
        report = latest_report(temp_dir)
        assert report["ok"] is False
        failed = {check["name"]: check for check in report["checks"] if check["status"] == "fail"}
        assert "configuration:transfer_quantization" in failed
        assert "unsupported PERMEANT_TRANSFER_QUANTIZATION: turboquant" in failed["configuration:transfer_quantization"]["message"]


def test_preflight_fails_when_profile_model_does_not_match():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(
            temp_dir,
            PERMEANT_VALIDATION_PROFILE="gemma-2-2b-it-mlx-vllm",
            PERMEANT_MODEL="Qwen/Qwen2.5-0.5B-Instruct",
        )

        assert result.returncode == 1
        report = latest_report(temp_dir)
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["configuration:validation_profile"]["status"] == "fail"
        assert "expects PERMEANT_MODEL=google/gemma-2-2b-it" in checks["configuration:validation_profile"]["message"]


def test_preflight_accepts_custom_model_profile_when_identity_is_explicit():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(
            temp_dir,
            PERMEANT_VALIDATION_PROFILE="custom",
            PERMEANT_MODEL="example/model",
            PERMEANT_MODEL_FAMILY="example-family",
            PERMEANT_SOURCE_RUNTIME="mlx",
            PERMEANT_TARGET_RUNTIME="vllm",
        )

        assert result.returncode == 0, result.stderr + result.stdout
        report = latest_report(temp_dir)
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["configuration:validation_profile"]["status"] == "pass"
        assert "example-family" in checks["configuration:validation_profile"]["message"]


def test_preflight_accepts_long_horizon_aws_profile():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(
            temp_dir,
            PERMEANT_VALIDATION_PROFILE="qwen2.5-0.5b-long-horizon-aws",
            PERMEANT_SEQ_LEN="1920",
            PERMEANT_CONTINUATION_MAX_TOKENS="128",
            PERMEANT_FIDELITY_HORIZONS="16,32,64,128",
            PERMEANT_TRANSFER_QUANTIZATION="qatq",
        )

        assert result.returncode == 0, result.stderr + result.stdout
        report = latest_report(temp_dir)
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["configuration:numeric"]["status"] == "pass"
        assert checks["configuration:validation_profile"]["status"] == "pass"


def test_preflight_applies_tinyllama_cache_geometry():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(
            temp_dir,
            PERMEANT_VALIDATION_PROFILE="tinyllama-1.1b-chat-mlx-vllm",
            PERMEANT_MODEL="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            PERMEANT_MODEL_FAMILY="llama",
            PERMEANT_SEQ_LEN="1984",
            PERMEANT_TRANSFER_QUANTIZATION="none",
        )

        assert result.returncode == 0, result.stderr + result.stdout
        latest = temp_dir / "state" / "latest"
        state = json.loads((latest / "state.json").read_text())
        assert state["model_layer_count"] == "22"
        assert state["model_q_heads"] == "32"
        assert state["model_kv_heads"] == "4"
        assert state["model_head_dim"] == "64"
        assert state["model_hidden_size"] == "2048"
        assert state["model_block_size"] == "256"


def test_preflight_fails_when_context_window_cannot_fit_continuation():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        result = run_preflight(
            temp_dir,
            PERMEANT_SEQ_LEN="2040",
            PERMEANT_VLLM_MAX_MODEL_LEN="2048",
            PERMEANT_CONTINUATION_MAX_TOKENS="16",
        )

        assert result.returncode == 1
        report = latest_report(temp_dir)
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["configuration:numeric"]["status"] == "fail"
        assert "migrated sequence plus continuation tokens" in checks["configuration:numeric"]["message"]


def test_preflight_passes_with_agent_graph_manifest():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        manifest = temp_dir / "manifest.json"
        manifest.write_text("{}")
        result = run_preflight(temp_dir, PERMEANT_AGENT_GRAPH_MANIFEST=str(manifest))

        assert result.returncode == 0, result.stderr + result.stdout
        report = latest_report(temp_dir)
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["source:agent_graph_manifest"]["status"] == "pass"
        assert str(manifest) in checks["source:agent_graph_manifest"]["message"]


def test_preflight_fails_for_missing_agent_graph_manifest():
    with tempfile.TemporaryDirectory() as raw_temp_dir:
        temp_dir = pathlib.Path(raw_temp_dir)
        missing_manifest = temp_dir / "missing-manifest.json"
        result = run_preflight(temp_dir, PERMEANT_AGENT_GRAPH_MANIFEST=str(missing_manifest))

        assert result.returncode == 1
        report = latest_report(temp_dir)
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["source:agent_graph_manifest"]["status"] == "fail"
        assert str(missing_manifest) in checks["source:agent_graph_manifest"]["message"]
