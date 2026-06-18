"""Helpers for preparing canonical tensors for a real vLLM-side injector."""

from __future__ import annotations

import inspect
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_adapter_utils import AdapterError, load_hook, normalize_injector_response



def _shape_of(value: Any) -> list[int]:
    shape: list[int] = []
    cursor = value
    while isinstance(cursor, list):
        shape.append(len(cursor))
        cursor = cursor[0] if cursor else []
    return shape



def _request_kind(request: dict[str, Any]) -> str:
    if "kind" in request and isinstance(request["kind"], str):
        return request["kind"]
    if "action" in request and isinstance(request["action"], str):
        return request["action"]
    if "inject_block" in request:
        return "inject_block"
    if "verify_continuation" in request:
        return "verify_continuation"
    if "tensors" in request and "hash" in request:
        return "inject_block"
    if "block_hashes" in request:
        return "verify_continuation"
    raise AdapterError("unable to determine injector request kind")



def _payload_for_kind(request: dict[str, Any], kind: str) -> dict[str, Any]:
    nested = request.get(kind)
    if isinstance(nested, dict):
        return nested
    return request



def _group_layers(tensors: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for tensor in tensors:
        name = tensor.get("name")
        if not isinstance(name, str):
            raise AdapterError("injector tensor name must be a string")
        parts = name.split(".")
        if len(parts) != 3 or parts[0] != "layer" or parts[2] not in {"key", "value"}:
            raise AdapterError(f"unexpected tensor name '{name}'")
        layer_index = int(parts[1])
        grouped.setdefault(layer_index, {})[parts[2]] = tensor
    return grouped



def _canonical_tensor_data(tensor: dict[str, Any]) -> list[Any]:
    data = tensor.get("data")
    shape = tensor.get("shape")
    if not isinstance(data, list):
        raise AdapterError(f"tensor {tensor.get('name')} must contain a list payload")
    if isinstance(shape, list) and len(shape) == 3 and all(isinstance(x, int) for x in shape):
        expected = shape[0] * shape[1] * shape[2]
        if len(data) != expected:
            raise AdapterError(
                f"tensor {tensor.get('name')} flat payload length {len(data)} does not match shape {shape}"
            )
        rebuilt = []
        offset = 0
        for seq_index in range(shape[0]):
            seq_slice = []
            for head_index in range(shape[1]):
                head_slice = data[offset : offset + shape[2]]
                seq_slice.append(head_slice)
                offset += shape[2]
            rebuilt.append(seq_slice)
        return rebuilt
    shape = _shape_of(data)
    if len(shape) != 3:
        raise AdapterError(f"tensor {tensor.get('name')} must be canonical [seq, kv_heads, head_dim], got {shape}")
    return data



def _key_to_blocks(data: list[Any], block_size: int) -> list[Any]:
    seq_len = len(data)
    kv_heads = len(data[0]) if data else 0
    head_dim = len(data[0][0]) if data and data[0] else 0
    num_blocks = max(1, math.ceil(seq_len / block_size))
    blocks = [
        [[[0.0 for _ in range(block_size)] for _ in range(head_dim)] for _ in range(kv_heads)]
        for _ in range(num_blocks)
    ]
    for seq_index in range(seq_len):
        block_index = seq_index // block_size
        offset = seq_index % block_size
        for head_index in range(kv_heads):
            for dim_index in range(head_dim):
                blocks[block_index][head_index][dim_index][offset] = data[seq_index][head_index][dim_index]
    return blocks



def _value_to_blocks(data: list[Any], block_size: int) -> list[Any]:
    seq_len = len(data)
    kv_heads = len(data[0]) if data else 0
    head_dim = len(data[0][0]) if data and data[0] else 0
    num_blocks = max(1, math.ceil(seq_len / block_size))
    blocks = [
        [[[0.0 for _ in range(head_dim)] for _ in range(block_size)] for _ in range(kv_heads)]
        for _ in range(num_blocks)
    ]
    for seq_index in range(seq_len):
        block_index = seq_index // block_size
        offset = seq_index % block_size
        for head_index in range(kv_heads):
            for dim_index in range(head_dim):
                blocks[block_index][head_index][offset][dim_index] = data[seq_index][head_index][dim_index]
    return blocks



def prepare_injected_block_state(request: dict[str, Any]) -> dict[str, Any]:
    payload = _payload_for_kind(request, "inject_block")
    block_hash = payload.get("hash") or payload.get("block_hash")
    if not isinstance(block_hash, str) or not block_hash:
        raise AdapterError("inject_block request must include a non-empty 'hash'")

    tensors = payload.get("tensors")
    if not isinstance(tensors, list) or not tensors:
        raise AdapterError("inject_block request must include a non-empty 'tensors' list")

    block_size = int(payload.get("block_size") or os.getenv("PERMEANT_VLLM_BLOCK_SIZE") or 256)
    grouped = _group_layers(tensors)

    layers: list[dict[str, Any]] = []
    for layer_index in sorted(grouped):
        layer = grouped[layer_index]
        if "key" not in layer or "value" not in layer:
            raise AdapterError(f"layer {layer_index} is missing key/value tensors")
        key_shape = layer["key"].get("shape")
        value_shape = layer["value"].get("shape")
        if (
            isinstance(key_shape, list)
            and isinstance(value_shape, list)
            and len(key_shape) == 4
            and len(value_shape) == 4
        ):
            layers.append(
                {
                    "layer_index": layer_index,
                    "shape_mode": "preblocked",
                    "key_tensor": layer["key"],
                    "value_tensor": layer["value"],
                }
            )
            continue
        key_data = _canonical_tensor_data(layer["key"])
        value_data = _canonical_tensor_data(layer["value"])
        layers.append(
            {
                "layer_index": layer_index,
                "seq_len": len(key_data),
                "kv_heads": len(key_data[0]) if key_data else 0,
                "head_dim": len(key_data[0][0]) if key_data and key_data[0] else 0,
                "key_blocks": _key_to_blocks(key_data, block_size),
                "value_blocks": _value_to_blocks(value_data, block_size),
            }
        )

    return {
        "hash": block_hash,
        "block_size": block_size,
        "layer_count": len(layers),
        "layers": layers,
    }



def persist_prepared_block(state: dict[str, Any], state_dir: str | None = None) -> Path | None:
    directory = state_dir or os.getenv("PERMEANT_VLLM_STATE_DIR")
    if not directory:
        return None
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    output = path / f"{state['hash']}.json"
    output.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return output



def _call_runtime_hook(hook: Callable[..., Any], primary: Any, request: dict[str, Any]) -> Any:
    try:
        signature = inspect.signature(hook)
    except (TypeError, ValueError):
        return hook(primary, request)

    positional = [
        p
        for p in signature.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(positional) <= 1:
        return hook(primary)
    return hook(primary, request)



def runtime_hook_from_env() -> Callable[..., Any] | None:
    spec = os.getenv("PERMEANT_VLLM_RUNTIME_HOOK")
    if not spec:
        return None
    return load_hook(spec)



def verify_hashes_from_state_dir(request: dict[str, Any]) -> dict[str, Any]:
    payload = _payload_for_kind(request, "verify_continuation")
    hashes = payload.get("block_hashes") or payload.get("expected_hashes")
    if not isinstance(hashes, list) or not all(isinstance(item, str) for item in hashes):
        raise AdapterError("verify_continuation requires a string list in 'block_hashes'")

    state_dir = os.getenv("PERMEANT_VLLM_STATE_DIR")
    if not state_dir:
        return {"success": True}

    available = {item.stem for item in Path(state_dir).glob("*.json")}
    missing = [item for item in hashes if item not in available]
    if missing:
        return {"success": False, "missing_hashes": missing}
    return {"success": True}



def injector_hook(request: dict[str, Any]) -> dict[str, Any]:
    kind = _request_kind(request)
    runtime_hook = runtime_hook_from_env()

    if kind == "inject_block":
        prepared = prepare_injected_block_state(request)
        persist_prepared_block(prepared)
        if runtime_hook is not None:
            return normalize_injector_response(_call_runtime_hook(runtime_hook, prepared, request))
        return {"success": True}

    if kind == "verify_continuation":
        payload = _payload_for_kind(request, "verify_continuation")
        hashes = payload.get("block_hashes") or payload.get("expected_hashes")
        normalized_payload = {"block_hashes": hashes} if isinstance(hashes, list) else payload
        if runtime_hook is not None:
            return normalize_injector_response(_call_runtime_hook(runtime_hook, normalized_payload, request))
        return normalize_injector_response(verify_hashes_from_state_dir(request))

    raise AdapterError(f"unsupported injector request kind '{kind}'")
