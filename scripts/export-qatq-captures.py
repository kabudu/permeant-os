#!/usr/bin/env python3
"""Export selected live MLX KV tensors as QATQ `.f32le` fixtures.

This is intentionally a PermeantOS evidence helper, not a QATQ integration
path. It loads a real MLX source runtime through the existing live runtime
provider, prefills the largest requested sequence length, and writes selected
canonical KV tensors as raw little-endian IEEE-754 f32 files with no header.
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
from mlx_runtime_bridge import _canonicalize_tensor, extract_cache_layers  # noqa: E402


def _parse_csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _stable_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "model"


def _layer_indices(layer_count: int, points: str) -> list[int]:
    if points == "early-middle-late":
        candidates = [0, layer_count // 2, layer_count - 1]
    else:
        candidates = _parse_csv_ints(points)
    result: list[int] = []
    for index in candidates:
        if index < 0:
            index = layer_count + index
        if index < 0 or index >= layer_count:
            raise SystemExit(f"layer index {index} outside available layer range 0..{layer_count - 1}")
        if index not in result:
            result.append(index)
    return result


def _dtype_name(tensor: Any) -> str:
    dtype = getattr(tensor, "dtype", None)
    return str(dtype) if dtype is not None else "unknown"


def _write_f32le(path: Path, data: Any) -> tuple[int, int, str]:
    array = np.asarray(data, dtype="<f4")
    if not array.flags["C_CONTIGUOUS"]:
        array = np.ascontiguousarray(array)
    raw = array.tobytes(order="C")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return array.size, len(raw), hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="MLX-LM model id to load")
    parser.add_argument("--model-family", required=True)
    parser.add_argument("--seq-lens", required=True, help="Comma-separated sequence lengths to export")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--runtime-path", required=True)
    parser.add_argument("--layer-points", default="early-middle-late")
    parser.add_argument("--tensor-roles", default="key,value")
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args()

    seq_lens = sorted(set(_parse_csv_ints(args.seq_lens)))
    if not seq_lens:
        raise SystemExit("--seq-lens must contain at least one positive integer")
    max_seq_len = max(seq_lens)

    os.environ["PERMEANT_MLX_MODEL_ID"] = args.model
    os.environ["PERMEANT_MLX_TARGET_SEQ_LEN"] = str(max_seq_len)

    runtime = mlx_live_runtime._ensure_runtime(max_seq_len)
    layers = extract_cache_layers(runtime.caches)
    layer_indices = _layer_indices(len(layers), args.layer_points)
    roles = [role.strip() for role in args.tensor_roles.split(",") if role.strip()]
    invalid_roles = [role for role in roles if role not in {"key", "value"}]
    if invalid_roles:
        raise SystemExit(f"unsupported tensor roles: {', '.join(invalid_roles)}")

    model_slug = _stable_slug(args.model)
    captures: list[dict[str, Any]] = []
    for seq_len in seq_lens:
        for layer_index in layer_indices:
            key_tensor, value_tensor = layers[layer_index]
            role_pairs = {
                "key": key_tensor,
                "value": value_tensor,
            }
            for role in roles:
                source_tensor = role_pairs[role]
                canonical = _canonicalize_tensor(f"layer.{layer_index}.{role}", source_tensor, seq_len)
                name = f"{model_slug}-seq{seq_len}-layer{layer_index}-{role}"
                path = args.output_dir / f"{name}.f32le"
                value_count, byte_count, sha256 = _write_f32le(path, canonical)
                captures.append(
                    {
                        "name": name,
                        "model": args.model,
                        "model_family": args.model_family,
                        "scenario": args.scenario,
                        "runtime_path": args.runtime_path,
                        "source_tensor": f"layer.{layer_index}.{role}",
                        "tensor_role": role,
                        "shape": [seq_len, len(canonical[0]) if canonical else 0, len(canonical[0][0]) if canonical and canonical[0] else 0],
                        "value_count": value_count,
                        "byte_count": byte_count,
                        "sha256": sha256,
                        "runtime_tensor_dtype": _dtype_name(source_tensor),
                        "export_dtype": "raw-little-endian-ieee754-f32-no-header",
                        "path": str(path),
                        "manifest_path": str(path),
                        "run_id": args.run_id,
                    }
                )

    payload = {
        "schema_version": "permeantos-qatq-capture-metadata-v1",
        "run_id": args.run_id,
        "model": args.model,
        "model_family": args.model_family,
        "source_runtime": "mlx-live-runtime",
        "max_seq_len": max_seq_len,
        "prompt_token_count": len(runtime.prompt_tokens),
        "capture_count": len(captures),
        "captures": captures,
    }

    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
