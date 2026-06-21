#!/usr/bin/env python3
"""Export a live MLX prompt KV cache for the llama.cpp raw KV writer proof.

The output is intentionally simple: one tab-separated manifest, one prompt
text file, and raw little-endian f32 files for every canonical K/V layer. The
llama.cpp proof bridge consumes this directly and performs tokenizer/span,
position, geometry, corruption, and continuation checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = ROOT_DIR / "adapters"
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))

import mlx_live_runtime  # noqa: E402
from mlx_lm import batch_generate  # noqa: E402
from mlx_runtime_bridge import _canonicalize_tensor, extract_cache_layers  # noqa: E402


def _stable_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "model"


def _write_f32le(path: Path, data: Any) -> tuple[list[int], int, str]:
    array = np.asarray(data, dtype="<f4")
    if array.ndim != 3:
        raise SystemExit(f"canonical tensor must be 3D, got shape {array.shape}")
    if not array.flags["C_CONTIGUOUS"]:
        array = np.ascontiguousarray(array)
    raw = array.tobytes(order="C")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return [int(dim) for dim in array.shape], len(raw), hashlib.sha256(raw).hexdigest()


def _extract_generated_text(response: Any, prompt: str) -> str:
    for attr_name in ("text", "texts", "outputs", "generations", "responses"):
        value = getattr(response, attr_name, None)
        if value is None:
            continue
        if isinstance(value, str):
            return value[len(prompt) :] if value.startswith(prompt) else value
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return first[len(prompt) :] if first.startswith(prompt) else first
            for nested_attr in ("text", "output_text", "generated_text"):
                nested = getattr(first, nested_attr, None)
                if isinstance(nested, str):
                    return nested[len(prompt) :] if nested.startswith(prompt) else nested
    return ""


def _encode(tokenizer: Any, text: str) -> list[int]:
    encoded = tokenizer.encode(text)
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    return [int(token) for token in encoded]


def _continuation_tokens(runtime: mlx_live_runtime.LiveRuntime, max_tokens: int) -> tuple[str, list[int]]:
    response = batch_generate(
        runtime.model,
        runtime.tokenizer,
        prompts=[runtime.prompt_tokens],
        max_tokens=max_tokens,
        verbose=False,
    )
    text = _extract_generated_text(response, runtime.prompt_text)
    return text, _encode(runtime.tokenizer, text) if text else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--seq-len", type=int, default=18)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-prompt", help="Prompt seed to repeat until --seq-len tokens exist")
    parser.add_argument("--continuation-tokens", type=int, default=8)
    args = parser.parse_args()

    if args.seq_len <= 0:
        raise SystemExit("--seq-len must be positive")

    os.environ["PERMEANT_MLX_MODEL_ID"] = args.model
    os.environ["PERMEANT_MLX_TARGET_SEQ_LEN"] = str(args.seq_len)
    if args.base_prompt:
        os.environ["PERMEANT_MLX_BASE_PROMPT"] = args.base_prompt

    runtime = mlx_live_runtime._ensure_runtime(args.seq_len)
    layers = extract_cache_layers(runtime.caches)
    model_slug = _stable_slug(args.model)

    run_dir = args.output_dir.resolve()
    tensor_dir = run_dir / "tensors"
    prompt_path = run_dir / "prompt.txt"
    manifest_path = run_dir / "mlx-to-llamacpp-canonical-kv.tsv"
    metadata_path = run_dir / "metadata.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(runtime.prompt_text, encoding="utf-8")

    source_text, source_tokens = _continuation_tokens(runtime, args.continuation_tokens)

    manifest_lines = [
        "schema_version\tpermeantos-cross-runtime-canonical-kv-v0",
        "source_runtime\tmlx-live-runtime",
        f"source_model\t{args.model}",
        f"prompt_path\t{prompt_path}",
        "prompt_tokens\t" + ",".join(str(token) for token in runtime.prompt_tokens[: args.seq_len]),
        "source_token_ids\t" + ",".join(str(token) for token in source_tokens),
    ]
    tensor_metadata: list[dict[str, Any]] = []
    for layer_index, (key_tensor, value_tensor) in enumerate(layers):
        canonical_key = _canonicalize_tensor(f"layer.{layer_index}.key", key_tensor, args.seq_len)
        canonical_value = _canonicalize_tensor(f"layer.{layer_index}.value", value_tensor, args.seq_len)
        key_path = tensor_dir / f"{model_slug}-seq{args.seq_len}-layer{layer_index}-key.f32le"
        value_path = tensor_dir / f"{model_slug}-seq{args.seq_len}-layer{layer_index}-value.f32le"
        key_shape, key_bytes, key_sha256 = _write_f32le(key_path, canonical_key)
        value_shape, value_bytes, value_sha256 = _write_f32le(value_path, canonical_value)
        if key_shape[0] != args.seq_len or value_shape[0] != args.seq_len:
            raise SystemExit(f"layer {layer_index} did not export the requested sequence length")
        if key_shape[1:] != value_shape[1:]:
            raise SystemExit(f"layer {layer_index} key/value shape mismatch: {key_shape} vs {value_shape}")
        key_width = key_shape[1] * key_shape[2]
        value_width = value_shape[1] * value_shape[2]
        manifest_lines.append(
            "\t".join(
                [
                    "layer",
                    str(layer_index),
                    str(args.seq_len),
                    str(key_width),
                    str(value_width),
                    str(key_path),
                    str(value_path),
                    f"{key_sha256},{value_sha256}",
                ]
            )
        )
        tensor_metadata.append(
            {
                "layer_index": layer_index,
                "key_shape": key_shape,
                "value_shape": value_shape,
                "key_bytes": key_bytes,
                "value_bytes": value_bytes,
                "key_sha256": "sha256:" + key_sha256,
                "value_sha256": "sha256:" + value_sha256,
            }
        )

    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    metadata = {
        "schema_version": "permeantos-cross-runtime-canonical-kv-export-v0",
        "source_runtime": "mlx-live-runtime",
        "source_model": args.model,
        "seq_len": args.seq_len,
        "prompt_path": str(prompt_path),
        "manifest_path": str(manifest_path),
        "prompt_tokens": runtime.prompt_tokens[: args.seq_len],
        "source_continuation_text": source_text,
        "source_continuation_token_ids": source_tokens,
        "layer_count": len(tensor_metadata),
        "tensors": tensor_metadata,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
