from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "plan-context-benchmarks.py"
SPEC = importlib.util.spec_from_file_location("plan_context_benchmarks", MODULE_PATH)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def test_builds_larger_context_matrix_with_required_window():
    matrix = planner.build_matrix(
        sequence_lengths=[4096, 8192],
        quantization_modes=[False, True],
        continuation_max_tokens=32,
        tokenizer_overhead_tokens=16,
        repetitions=3,
        max_model_len_limit=None,
    )

    assert matrix["schema_version"] == "permeantos-context-benchmark-matrix-v0"
    assert len(matrix["points"]) == 4
    first = matrix["points"][0]
    assert first["sequence_length"] == 4096
    assert first["required_context_window"] == 4144
    assert first["valid"] is True
    assert first["runner_env"] == {
        "PERMEANT_SEQ_LEN": "4096",
        "PERMEANT_VLLM_MAX_MODEL_LEN": "4144",
        "PERMEANT_TRANSFER_QUANTIZATION": "none",
        "PERMEANT_CONTINUATION_MAX_TOKENS": "32",
        "PERMEANT_FIDELITY_HORIZONS": "16,32",
    }


def test_marks_points_invalid_when_not_larger_than_2k_or_over_limit():
    matrix = planner.build_matrix(
        sequence_lengths=[2048, 4096],
        quantization_modes=[False],
        continuation_max_tokens=64,
        tokenizer_overhead_tokens=32,
        repetitions=1,
        max_model_len_limit=4100,
    )

    short, capped = matrix["points"]
    assert short["valid"] is False
    assert short["invalid_reasons"] == ["sequence_length_not_larger_than_2k"]
    assert capped["valid"] is False
    assert capped["invalid_reasons"] == ["required_context_window_exceeds_limit"]


def test_runner_env_blocks_include_only_valid_points():
    matrix = planner.build_matrix(
        sequence_lengths=[2048, 4096],
        quantization_modes=[False],
        continuation_max_tokens=16,
        tokenizer_overhead_tokens=16,
        repetitions=1,
        max_model_len_limit=None,
    )

    output = planner.runner_env_blocks(matrix)

    assert "seq_len=2048" not in output
    assert "PERMEANT_SEQ_LEN=4096" in output
    assert "PERMEANT_VLLM_MAX_MODEL_LEN=4128" in output
    assert "PERMEANT_TRANSFER_QUANTIZATION=none" in output


def test_cli_style_outputs_markdown_and_env_blocks():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        markdown = root / "matrix.md"
        env_file = root / "matrix.env"
        matrix = planner.build_matrix(
            sequence_lengths=planner.parse_int_list("4096"),
            quantization_modes=planner.parse_bool_list("none,fp8"),
            continuation_max_tokens=16,
            tokenizer_overhead_tokens=16,
            repetitions=2,
            max_model_len_limit=None,
        )
        markdown.write_text(planner.markdown_table(matrix))
        env_file.write_text(planner.runner_env_blocks(matrix))

        assert "| 4096 | none | 4128 | 16 | 2 | True |" in markdown.read_text()
        assert "# seq_len=4096 quantization=none" in env_file.read_text()
        assert "# seq_len=4096 quantization=fp8" in env_file.read_text()


def test_matrix_json_is_serializable():
    matrix = planner.build_matrix(
        sequence_lengths=[32768],
        quantization_modes=[True],
        continuation_max_tokens=128,
        tokenizer_overhead_tokens=32,
        repetitions=3,
        max_model_len_limit=65536,
    )

    payload = json.loads(json.dumps(matrix))

    assert payload["points"][0]["required_context_window"] == 32928
    assert payload["points"][0]["source_env"]["PERMEANT_MLX_TARGET_SEQ_LEN"] == "32768"
    assert payload["points"][0]["source_env"]["PERMEANT_SOURCE_CONTINUATION_USE_PREFILL_PROMPT"] == "1"
