"""Concrete local target-process consumer hook.

This consumer stages one JSON descriptor per block into an import directory that a
local vLLM-adjacent process can watch. It is a stable spool format rather than a
private in-memory vLLM API.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runtime_adapter_utils import AdapterError


def _import_dir() -> Path:
    value = os.getenv("PERMEANT_VLLM_IMPORT_DIR")
    if not value:
        raise AdapterError("Set PERMEANT_VLLM_IMPORT_DIR for vllm_directory_consumer")
    path = Path(value)
    path.mkdir(parents=True, exist_ok=True)
    return path


def consume(payload: dict[str, Any]) -> dict[str, Any]:
    block_hash = payload.get("hash")
    if not isinstance(block_hash, str) or not block_hash:
        return {"success": False, "error": "payload hash missing"}
    import_dir = _import_dir()
    layers = []
    for layer in payload.get("layers", []):
        layer_record = {
            "layer_index": layer.get("layer_index"),
            "shape_mode": layer.get("shape_mode", "canonical"),
            "seq_len": layer.get("seq_len"),
            "kv_heads": layer.get("kv_heads"),
            "head_dim": layer.get("head_dim"),
            "key_blocks_path": f"{block_hash}.json",
            "value_blocks_path": f"{block_hash}.json",
        }
        key_tensor = layer.get("key_tensor")
        value_tensor = layer.get("value_tensor")
        if isinstance(key_tensor, dict):
            layer_record["key_tensor_name"] = key_tensor.get("name")
            layer_record["key_tensor_shape"] = key_tensor.get("shape")
        if isinstance(value_tensor, dict):
            layer_record["value_tensor_name"] = value_tensor.get("name")
            layer_record["value_tensor_shape"] = value_tensor.get("shape")
        layers.append(layer_record)
    record = {
        "hash": block_hash,
        "block_size": payload.get("block_size"),
        "layer_count": payload.get("layer_count"),
        "layers": layers,
    }
    (import_dir / f"{block_hash}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (import_dir / f"{block_hash}.ready.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"success": True}
