from __future__ import annotations

import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLANNER = ROOT / "scripts" / "plan-model-runtime-validations.py"


def run_planner(*args: str):
    return subprocess.run(
        [str(PLANNER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_planner_lists_validation_profiles_as_json():
    result = run_planner()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "permeantos-model-runtime-validation-plan-v0"
    names = {profile["name"] for profile in payload["profiles"]}
    assert "qwen2.5-0.5b-mlx-vllm" in names
    assert "qwen2.5-0.5b-long-horizon-aws" in names
    assert "tinyllama-1.1b-chat-mlx-vllm" in names
    assert "gemma-2-2b-it-mlx-vllm" in names
    assert "phi-3.5-mini-mlx-vllm" in names


def test_planner_emits_shell_command_for_specific_run_profile():
    result = run_planner("--profile", "qwen2.5-1.5b-mlx-vllm", "--format", "shell", "--action", "run")

    assert result.returncode == 0, result.stderr
    assert "PERMEANT_VALIDATION_PROFILE=qwen2.5-1.5b-mlx-vllm" in result.stdout
    assert "PERMEANT_MODEL=Qwen/Qwen2.5-1.5B-Instruct" in result.stdout
    assert "PERMEANT_FIDELITY_HORIZONS=16,32,64,128" in result.stdout
    assert "PERMEANT_MIGRATION_TRANSPORT=production-wss" in result.stdout
    assert "PERMEANT_TRANSFER_QUANTIZATION=none" in result.stdout
    assert result.stdout.strip().endswith("scripts/aws-real-runtime-e2e.sh run")


def test_planner_uses_raw_transfer_for_future_breadth_profiles():
    result = run_planner()

    assert result.returncode == 0, result.stderr
    profiles = {profile["name"]: profile for profile in json.loads(result.stdout)["profiles"]}
    assert profiles["qwen2.5-1.5b-mlx-vllm"]["transfer_quantization"] == "none"
    assert profiles["tinyllama-1.1b-chat-mlx-vllm"]["transfer_quantization"] == "none"
    assert profiles["gemma-2-2b-it-mlx-vllm"]["transfer_quantization"] == "none"
    assert profiles["phi-3.5-mini-mlx-vllm"]["transfer_quantization"] == "none"


def test_planner_qwen_1_5b_profile_leaves_continuation_headroom():
    result = run_planner("--profile", "qwen2.5-1.5b-mlx-vllm")

    assert result.returncode == 0, result.stderr
    profile = json.loads(result.stdout)["profiles"][0]
    assert profile["seq_len"] == 1984
    assert profile["continuation_tokens"] == 16
    assert profile["seq_len"] + profile["continuation_tokens"] < profile["max_model_len"]
    assert profile["env"]["PERMEANT_SEQ_LEN"] == "1984"
    assert profile["env"]["PERMEANT_TRANSFER_QUANTIZATION"] == "none"


def test_planner_emits_model_cache_geometry_for_tinyllama_profile():
    result = run_planner("--profile", "tinyllama-1.1b-chat-mlx-vllm")

    assert result.returncode == 0, result.stderr
    profile = json.loads(result.stdout)["profiles"][0]
    assert profile["layer_count"] == 22
    assert profile["q_heads"] == 32
    assert profile["kv_heads"] == 4
    assert profile["head_dim"] == 64
    assert profile["hidden_size"] == 2048
    assert profile["block_size"] == 256
    assert profile["env"]["PERMEANT_MODEL_KV_HEADS"] == "4"
    assert profile["env"]["PERMEANT_MODEL_LAYER_COUNT"] == "22"


def test_planner_long_horizon_profile_leaves_context_headroom():
    result = run_planner("--profile", "qwen2.5-0.5b-long-horizon-aws")

    assert result.returncode == 0, result.stderr
    profile = json.loads(result.stdout)["profiles"][0]
    assert profile["seq_len"] == 1920
    assert profile["continuation_tokens"] == 128
    assert profile["seq_len"] + profile["continuation_tokens"] == profile["max_model_len"]
    assert profile["env"]["PERMEANT_CONTINUATION_MAX_TOKENS"] == "128"


def test_planner_rejects_unknown_profile():
    result = run_planner("--profile", "unknown-family")

    assert result.returncode != 0
    assert "unknown validation profile" in result.stderr
