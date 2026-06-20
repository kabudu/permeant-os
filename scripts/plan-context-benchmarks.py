#!/usr/bin/env python3
"""Plan larger-context PermeantOS benchmark points."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_SEQUENCE_LENGTHS = [4096, 8192, 16384, 32768]
DEFAULT_CONTINUATION_MAX_TOKENS = 16
DEFAULT_TOKENIZER_OVERHEAD_TOKENS = 16
DEFAULT_REPETITIONS = 3


def parse_int_list(value: str) -> list[int]:
    values = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        number = int(item)
        if number <= 0:
            raise ValueError("values must be positive integers")
        values.append(number)
    if not values:
        raise ValueError("at least one value is required")
    return sorted(set(values))


def parse_bool_list(value: str) -> list[bool]:
    mapping = {
        "false": False,
        "0": False,
        "none": False,
        "raw": False,
        "true": True,
        "1": True,
        "fp8": True,
        "quant": True,
    }
    values = []
    for item in value.split(","):
        key = item.strip().lower()
        if not key:
            continue
        if key not in mapping:
            raise ValueError(f"unsupported quantization value: {item}")
        values.append(mapping[key])
    if not values:
        raise ValueError("at least one quantization value is required")
    return sorted(set(values))


def required_context_window(seq_len: int, continuation_max_tokens: int, tokenizer_overhead_tokens: int) -> int:
    return seq_len + continuation_max_tokens + tokenizer_overhead_tokens


def build_matrix(
    sequence_lengths: list[int],
    quantization_modes: list[bool],
    continuation_max_tokens: int,
    tokenizer_overhead_tokens: int,
    repetitions: int,
    max_model_len_limit: int | None,
) -> dict[str, Any]:
    points = []
    for seq_len in sequence_lengths:
        required_window = required_context_window(
            seq_len=seq_len,
            continuation_max_tokens=continuation_max_tokens,
            tokenizer_overhead_tokens=tokenizer_overhead_tokens,
        )
        for quantized in quantization_modes:
            valid = seq_len > 2048 and (max_model_len_limit is None or required_window <= max_model_len_limit)
            reasons = []
            if seq_len <= 2048:
                reasons.append("sequence_length_not_larger_than_2k")
            if max_model_len_limit is not None and required_window > max_model_len_limit:
                reasons.append("required_context_window_exceeds_limit")
            points.append(
                {
                    "sequence_length": seq_len,
                    "transfer_quantization": "fp8" if quantized else "none",
                    "quantized": quantized,
                    "continuation_max_tokens": continuation_max_tokens,
                    "tokenizer_overhead_tokens": tokenizer_overhead_tokens,
                    "required_context_window": required_window,
                    "repetitions": repetitions,
                    "valid": valid,
                    "invalid_reasons": reasons,
                    "runner_env": {
                        "PERMEANT_SEQ_LEN": str(seq_len),
                        "PERMEANT_VLLM_MAX_MODEL_LEN": str(required_window),
                        "PERMEANT_TRANSFER_QUANTIZATION": "fp8" if quantized else "none",
                        "PERMEANT_CONTINUATION_MAX_TOKENS": str(continuation_max_tokens),
                        "PERMEANT_FIDELITY_HORIZONS": ",".join(
                            str(item)
                            for item in default_horizons(continuation_max_tokens)
                        ),
                    },
                    "source_env": {
                        "PERMEANT_MLX_TARGET_SEQ_LEN": str(seq_len),
                        "PERMEANT_SOURCE_CONTINUATION_MAX_TOKENS": str(continuation_max_tokens),
                        "PERMEANT_SOURCE_CONTINUATION_FILE": "/tmp/permeant-source-continuation.json",
                        "PERMEANT_SOURCE_CONTINUATION_USE_PREFILL_PROMPT": "1",
                    },
                }
            )
    return {
        "schema_version": "permeantos-context-benchmark-matrix-v0",
        "sequence_lengths": sequence_lengths,
        "continuation_max_tokens": continuation_max_tokens,
        "tokenizer_overhead_tokens": tokenizer_overhead_tokens,
        "max_model_len_limit": max_model_len_limit,
        "repetitions": repetitions,
        "points": points,
    }


def default_horizons(continuation_max_tokens: int) -> list[int]:
    candidates = [16, 32, 64, 128]
    return [item for item in candidates if item <= continuation_max_tokens] or [continuation_max_tokens]


def markdown_table(matrix: dict[str, Any]) -> str:
    lines = [
        "| Seq len | Quantization | Required context window | Continuation tokens | Repetitions | Valid |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for point in matrix["points"]:
        lines.append(
            "| {sequence_length} | {transfer_quantization} | {required_context_window} | {continuation_max_tokens} | {repetitions} | {valid} |".format(
                **point
            )
        )
    return "\n".join(lines) + "\n"


def runner_env_blocks(matrix: dict[str, Any]) -> str:
    blocks = []
    for point in matrix["points"]:
        if not point["valid"]:
            continue
        env = point["runner_env"]
        blocks.append(
            "\n".join(
                [
                    f"# seq_len={point['sequence_length']} quantization={point['transfer_quantization']}",
                    f"PERMEANT_SEQ_LEN={env['PERMEANT_SEQ_LEN']} \\",
                    f"PERMEANT_VLLM_MAX_MODEL_LEN={env['PERMEANT_VLLM_MAX_MODEL_LEN']} \\",
                    f"PERMEANT_TRANSFER_QUANTIZATION={env['PERMEANT_TRANSFER_QUANTIZATION']} \\",
                    f"PERMEANT_CONTINUATION_MAX_TOKENS={env['PERMEANT_CONTINUATION_MAX_TOKENS']} \\",
                    f"PERMEANT_FIDELITY_HORIZONS={env['PERMEANT_FIDELITY_HORIZONS']} \\",
                    "scripts/aws-real-runtime-e2e.sh run",
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seq-lens", default=",".join(str(item) for item in DEFAULT_SEQUENCE_LENGTHS))
    parser.add_argument("--quantization", default="none,fp8", help="Comma list: none,fp8")
    parser.add_argument("--continuation-max-tokens", type=int, default=DEFAULT_CONTINUATION_MAX_TOKENS)
    parser.add_argument("--tokenizer-overhead-tokens", type=int, default=DEFAULT_TOKENIZER_OVERHEAD_TOKENS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--max-model-len-limit", type=int)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--env-out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if args.continuation_max_tokens <= 0:
        raise SystemExit("--continuation-max-tokens must be positive")
    if args.tokenizer_overhead_tokens < 0:
        raise SystemExit("--tokenizer-overhead-tokens must be zero or positive")
    if args.repetitions <= 0:
        raise SystemExit("--repetitions must be positive")

    matrix = build_matrix(
        sequence_lengths=parse_int_list(args.seq_lens),
        quantization_modes=parse_bool_list(args.quantization),
        continuation_max_tokens=args.continuation_max_tokens,
        tokenizer_overhead_tokens=args.tokenizer_overhead_tokens,
        repetitions=args.repetitions,
        max_model_len_limit=args.max_model_len_limit,
    )
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown_table(matrix))
    if args.env_out:
        args.env_out.parent.mkdir(parents=True, exist_ok=True)
        args.env_out.write_text(runner_env_blocks(matrix))
    print(json.dumps(matrix, indent=2 if args.pretty else None, sort_keys=True))


if __name__ == "__main__":
    main()
