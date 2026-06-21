"""Live target-runtime registration hook for vLLM-adjacent runtimes.

This hook supports two integration styles:
- method-driven runtimes implementing explicit registration / verification APIs
- direct KV-cache writing into a vLLM-style `kv_caches` mapping

The direct KV-cache path is based on current upstream vLLM source layouts where
model runners and KV connector adapters register `kv_caches` as a
`dict[str, tensor_like]` keyed by layer name. The tensor-like cache storage may
be either:
- a combined KV tensor such as `[num_blocks, 2, block_size, num_heads, head_dim]`
- a combined KV tensor such as `[num_blocks, 2, num_heads, block_size, head_dim]`
- separate key/value tensors exposed as a `(key_cache, value_cache)` pair or
  `{"key": ..., "value": ...}` mapping

Environment:
- PERMEANT_VLLM_RUNTIME_TARGET: required `module:symbol` or `/path/to/file.py:symbol`
- PERMEANT_VLLM_RUNTIME_REGISTER_METHOD: optional, defaults to `register_permeant_block`
- PERMEANT_VLLM_RUNTIME_VERIFY_METHOD: optional, defaults to `verify_permeant_hashes`
- PERMEANT_VLLM_RUNTIME_STATE_FILE: optional JSON state file storing registered hashes
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_REGISTERED_HASHES: set[str] = set()
_LAYER_PATTERNS = [
    re.compile(r"(?:^|\.)layers?\.(\d+)(?:\.|$)"),
    re.compile(r"(?:^|_)layer_(\d+)(?:_|$)"),
    re.compile(r"(?:^|\.)layer\.(\d+)(?:\.|$)"),
]


def _state_file() -> Path | None:
    value = os.getenv("PERMEANT_VLLM_RUNTIME_STATE_FILE")
    if not value:
        return None
    return Path(value).expanduser()


def _load_state_hashes() -> set[str]:
    path = _state_file()
    if path is None or not path.exists():
        return set()
    payload = json.loads(path.read_text())
    hashes = payload.get("registered_hashes", [])
    if not isinstance(hashes, list):
        return set()
    return {item for item in hashes if isinstance(item, str)}


def _store_hash(hash_value: str) -> None:
    _REGISTERED_HASHES.add(hash_value)
    path = _state_file()
    if path is None:
        return
    existing = _load_state_hashes()
    existing.add(hash_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"registered_hashes": sorted(existing)}, indent=2))


def _note_runtime_hash(runtime: Any, hash_value: str) -> None:
    try:
        hashes = getattr(runtime, "registered_hashes")
    except AttributeError:
        try:
            setattr(runtime, "registered_hashes", {hash_value})
        except Exception:
            return
        return

    if isinstance(hashes, set):
        hashes.add(hash_value)
    elif isinstance(hashes, list):
        if hash_value not in hashes:
            hashes.append(hash_value)


def _normalize_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {"success": True}
    if isinstance(result, bool):
        return {"success": result}
    if isinstance(result, dict):
        success = result.get("success")
        if success is None:
            normalized = dict(result)
            normalized["success"] = True
            return normalized
        return dict(result)
    raise TypeError(f"runtime hook returned unsupported result type: {type(result).__name__}")


def _supported_args(callable_obj: Any) -> int | None:
    signature = inspect.signature(callable_obj)
    positional = [
        param
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values()):
        return None
    return len(positional)


def _invoke(callable_obj: Any, *candidate_args: Any) -> Any:
    arg_count = _supported_args(callable_obj)
    if arg_count is None:
        return callable_obj(*candidate_args)
    return callable_obj(*candidate_args[:arg_count])


def _load_symbol(spec: str) -> Any:
    module_part, symbol_name = spec.rsplit(":", 1)
    module_part = module_part.strip()
    symbol_name = symbol_name.strip()
    path = Path(module_part).expanduser()

    if module_part.endswith(".py") or path.exists():
        resolved = path.resolve()
        module_name = f"permeant_vllm_runtime_{resolved.stem}_{abs(hash(str(resolved)))}"
        module = sys.modules.get(module_name)
        if module is None:
            module_spec = importlib.util.spec_from_file_location(module_name, resolved)
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError(f"unable to load runtime module from {resolved}")
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[module_name] = module
            module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_part)

    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        raise RuntimeError(f"runtime target symbol '{symbol_name}' not found in '{module_part}'") from exc


def _resolve_runtime(payload: dict[str, Any], request: dict[str, Any] | None) -> Any:
    spec = os.getenv("PERMEANT_VLLM_RUNTIME_TARGET")
    if not spec:
        raise RuntimeError("set PERMEANT_VLLM_RUNTIME_TARGET for live target-runtime registration")
    symbol = _load_symbol(spec)
    if callable(symbol):
        return _invoke(symbol, payload, request)
    return symbol


def _register_method_name() -> str:
    return os.getenv("PERMEANT_VLLM_RUNTIME_REGISTER_METHOD", "register_permeant_block")


def _verify_method_name() -> str:
    return os.getenv("PERMEANT_VLLM_RUNTIME_VERIFY_METHOD", "verify_permeant_hashes")


def _reverse_export_method_name() -> str:
    return os.getenv("PERMEANT_VLLM_RUNTIME_REVERSE_EXPORT_METHOD", "export_reverse_runtime_state")


def _verify_from_state(block_hashes: list[str]) -> dict[str, Any]:
    available = set(_REGISTERED_HASHES) | _load_state_hashes()
    missing = [hash_value for hash_value in block_hashes if hash_value not in available]
    if missing:
        return {"success": False, "missing_hashes": missing}
    return {"success": True}


def _shape_of_storage(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            return [int(item) for item in shape]
        except Exception:
            pass

    dims: list[int] = []
    cursor = value
    while isinstance(cursor, (list, tuple)):
        dims.append(len(cursor))
        cursor = cursor[0] if cursor else []
    return dims


def _preview_flat_values(value: Any, limit: int = 8) -> list[float]:
    if value is None or limit <= 0:
        return []

    if hasattr(value, "detach") and hasattr(value, "reshape"):
        try:
            flat = value.detach().cpu().reshape(-1)
            count = min(limit, int(flat.numel()))
            return [float(flat[index].item()) for index in range(count)]
        except Exception:
            pass

    preview: list[float] = []

    def walk(node: Any) -> None:
        if len(preview) >= limit:
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
                if len(preview) >= limit:
                    return
            return
        try:
            preview.append(float(node))
        except Exception:
            return

    walk(value)
    return preview


def _scalar(value: Any) -> float:
    if hasattr(value, "detach"):
        try:
            return float(value.detach().cpu().item())
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return float(value.item())
        except Exception:
            pass
    return float(value)


def _source_value(
    key_source: Any,
    value_source: Any,
    is_flat: bool,
    block_index: int,
    head_index: int,
    dim_index: int,
    token_index: int,
) -> tuple[float, float]:
    if is_flat:
        key_value, value_value = _flat_key_value(
            key_source,
            value_source,
            block_index,
            head_index,
            dim_index,
            token_index,
        )
    else:
        key_value = key_source[block_index][head_index][dim_index][token_index]
        value_value = value_source[block_index][head_index][token_index][dim_index]
    return float(key_value), float(value_value)


def _prepared_layer_summary(layer: dict[str, Any]) -> dict[str, Any]:
    key_source, value_source, block_size, kv_heads, head_dim, is_flat = _layer_block_views(layer)
    source_block_count = _source_block_count(key_source, is_flat)
    if is_flat:
        key_preview = [float(item) for item in key_source["data"][:8]]
        value_preview = [float(item) for item in value_source["data"][:8]]
    else:
        key_preview = _preview_flat_values(key_source, 8)
        value_preview = _preview_flat_values(value_source, 8)

    return {
        "block_count": source_block_count,
        "block_size": block_size,
        "kv_heads": kv_heads,
        "head_dim": head_dim,
        "key_shape": key_source.get("shape") if is_flat else _shape_of_storage(key_source),
        "value_shape": value_source.get("shape") if is_flat else _shape_of_storage(value_source),
        "key_preview": key_preview,
        "value_preview": value_preview,
    }


def _sample_points(source_block_count: int, block_size: int, kv_heads: int, head_dim: int) -> list[dict[str, int]]:
    candidates = [
        {"block_index": 0, "token_index": 0, "head_index": 0, "dim_index": 0},
        {
            "block_index": 0,
            "token_index": min(block_size - 1, 1),
            "head_index": min(kv_heads - 1, 1),
            "dim_index": min(head_dim - 1, 1),
        },
        {
            "block_index": max(source_block_count - 1, 0),
            "token_index": max(block_size - 1, 0),
            "head_index": max(kv_heads - 1, 0),
            "dim_index": max(head_dim - 1, 0),
        },
    ]
    seen: set[tuple[int, int, int, int]] = set()
    points: list[dict[str, int]] = []
    limit = int(os.getenv("PERMEANT_VLLM_SLOT_SAMPLE_LIMIT", "4"))
    for candidate in candidates:
        key = (
            candidate["block_index"],
            candidate["token_index"],
            candidate["head_index"],
            candidate["dim_index"],
        )
        if key in seen:
            continue
        seen.add(key)
        points.append(candidate)
        if len(points) >= limit:
            break
    return points


def _combined_layout(shape: list[int], block_size: int, kv_heads: int, head_dim: int) -> dict[str, Any]:
    if len(shape) != 5 or shape[1] != 2:
        return {"kind": "unsupported", "shape": shape}
    if shape[2] == block_size and shape[3] == kv_heads and shape[4] == head_dim:
        return {"kind": "combined_token_head_dim", "tokens_per_target_block": block_size}
    if shape[2] == kv_heads and shape[3] == block_size and shape[4] == head_dim:
        return {"kind": "combined_head_token_dim", "tokens_per_target_block": block_size}
    if shape[3] == kv_heads and shape[4] == head_dim and block_size % shape[2] == 0:
        return {
            "kind": "combined_split_token_head_dim",
            "tokens_per_target_block": shape[2],
            "target_blocks_per_source_block": block_size // shape[2],
        }
    if shape[2] == kv_heads and shape[4] == head_dim and block_size % shape[3] == 0:
        return {
            "kind": "combined_split_head_token_dim",
            "tokens_per_target_block": shape[3],
            "target_blocks_per_source_block": block_size // shape[3],
        }
    return {"kind": "unsupported", "shape": shape}


def _combined_target_indices(
    layout: dict[str, Any],
    block_index: int,
    token_index: int,
    head_index: int,
    dim_index: int,
    target_block_ids: list[int] | None = None,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    kind = layout.get("kind")
    tokens_per_target_block = int(layout.get("tokens_per_target_block") or 1)
    if kind in {"combined_split_token_head_dim", "combined_split_head_token_dim"}:
        target_block_index = block_index * int(layout.get("target_blocks_per_source_block") or 1) + (
            token_index // tokens_per_target_block
        )
        target_token_index = token_index % tokens_per_target_block
    else:
        target_block_index = block_index
        target_token_index = token_index
    target_block_index = _target_block_id(target_block_index, target_block_ids)

    if kind in {"combined_token_head_dim", "combined_split_token_head_dim"}:
        return (
            (target_block_index, 0, target_token_index, head_index, dim_index),
            (target_block_index, 1, target_token_index, head_index, dim_index),
        )
    if kind in {"combined_head_token_dim", "combined_split_head_token_dim"}:
        return (
            (target_block_index, 0, head_index, target_token_index, dim_index),
            (target_block_index, 1, head_index, target_token_index, dim_index),
        )
    raise RuntimeError(f"unsupported combined kv_cache layout sample {layout}")


def _value_at(value: Any, indices: tuple[int, ...]) -> float:
    cursor = value
    for index in indices:
        cursor = cursor[index]
    return _scalar(cursor)


def _combined_slot_samples(cache: Any, layer: dict[str, Any], target_block_ids: list[int] | None = None) -> dict[str, Any]:
    shape = _shape_of_storage(cache)
    key_source, value_source, block_size, kv_heads, head_dim, is_flat = _layer_block_views(layer)
    source_block_count = _source_block_count(key_source, is_flat)
    layout = _combined_layout(shape, block_size, kv_heads, head_dim)
    samples: list[dict[str, Any]] = []
    for point in _sample_points(source_block_count, block_size, kv_heads, head_dim):
        block_index = point["block_index"]
        token_index = point["token_index"]
        head_index = point["head_index"]
        dim_index = point["dim_index"]
        source_key, source_value = _source_value(
            key_source,
            value_source,
            is_flat,
            block_index,
            head_index,
            dim_index,
            token_index,
        )
        key_indices, value_indices = _combined_target_indices(
            layout,
            block_index,
            token_index,
            head_index,
            dim_index,
            target_block_ids,
        )
        target_key = _value_at(cache, key_indices)
        target_value = _value_at(cache, value_indices)
        key_delta = abs(source_key - target_key)
        value_delta = abs(source_value - target_value)
        samples.append(
            {
                "source": point,
                "target_key_indices": list(key_indices),
                "target_value_indices": list(value_indices),
                "source_key": source_key,
                "target_key": target_key,
                "source_value": source_value,
                "target_value": target_value,
                "key_delta": key_delta,
                "value_delta": value_delta,
                "key_matches": key_delta <= 1e-6,
                "value_matches": value_delta <= 1e-6,
            }
        )
    return {
        "layout": layout,
        "samples": samples,
        "all_samples_match": all(
            sample["key_matches"] and sample["value_matches"] for sample in samples
        ),
    }


def _cache_storage_summary(cache: Any) -> dict[str, Any]:
    if isinstance(cache, dict):
        key_cache = cache.get("key")
        value_cache = cache.get("value")
        return {
            "kind": "dict",
            "key_shape": _shape_of_storage(key_cache),
            "value_shape": _shape_of_storage(value_cache),
            "key_preview": _preview_flat_values(key_cache, 8),
            "value_preview": _preview_flat_values(value_cache, 8),
        }

    if isinstance(cache, (list, tuple)) and len(cache) == 2:
        key_cache, value_cache = cache
        return {
            "kind": "pair",
            "key_shape": _shape_of_storage(key_cache),
            "value_shape": _shape_of_storage(value_cache),
            "key_preview": _preview_flat_values(key_cache, 8),
            "value_preview": _preview_flat_values(value_cache, 8),
        }

    return {
        "kind": "tensor",
        "shape": _shape_of_storage(cache),
        "preview": _preview_flat_values(cache, 8),
    }


def _layer_index_from_name(name: str) -> int | None:
    for pattern in _LAYER_PATTERNS:
        match = pattern.search(name)
        if match:
            return int(match.group(1))
    return None


def _get_kv_caches(runtime: Any) -> dict[str, Any]:
    kv_caches = getattr(runtime, "kv_caches", None)
    if kv_caches is None:
        getter = getattr(runtime, "get_kv_caches", None)
        if callable(getter):
            kv_caches = _invoke(getter)
    if not isinstance(kv_caches, dict) or not kv_caches:
        raise RuntimeError("runtime object does not expose a non-empty kv_caches mapping")
    return kv_caches


def _get_layer_map(runtime: Any, kv_caches: dict[str, Any]) -> dict[int, str]:
    configured = getattr(runtime, "permeant_layer_map", None)
    if isinstance(configured, dict) and configured:
        normalized: dict[int, str] = {}
        for key, value in configured.items():
            if isinstance(key, int) and isinstance(value, str):
                normalized[key] = value
        if normalized:
            return normalized

    inferred: dict[int, str] = {}
    for layer_name in kv_caches:
        if not isinstance(layer_name, str):
            continue
        layer_index = _layer_index_from_name(layer_name)
        if layer_index is None:
            continue
        inferred.setdefault(layer_index, layer_name)
    if inferred:
        return inferred
    raise RuntimeError("unable to infer layer-name mapping from runtime kv_caches")


def _layer_block_views(layer: dict[str, Any]) -> tuple[Any, Any, int, int, int, bool]:
    key_blocks = layer.get("key_blocks")
    value_blocks = layer.get("value_blocks")
    if key_blocks is not None and value_blocks is not None:
        block_size = len(value_blocks[0][0]) if value_blocks and value_blocks[0] else 0
        kv_heads = len(key_blocks[0]) if key_blocks else 0
        head_dim = len(key_blocks[0][0]) if key_blocks and key_blocks[0] else 0
        return key_blocks, value_blocks, block_size, kv_heads, head_dim, False

    key_tensor = layer.get("key_tensor")
    value_tensor = layer.get("value_tensor")
    if not isinstance(key_tensor, dict) or not isinstance(value_tensor, dict):
        raise RuntimeError("prepared payload layer must expose key/value blocks or key_tensor/value_tensor")

    key_shape = key_tensor.get("shape")
    value_shape = value_tensor.get("shape")
    key_data = key_tensor.get("data")
    value_data = value_tensor.get("data")
    if (
        not isinstance(key_shape, list)
        or len(key_shape) != 4
        or not isinstance(value_shape, list)
        or len(value_shape) != 4
        or not isinstance(key_data, list)
        or not isinstance(value_data, list)
    ):
        raise RuntimeError("prepared key/value tensor payloads must include flat data with 4D shapes")

    block_size = int(key_shape[3])
    kv_heads = int(key_shape[1])
    head_dim = int(key_shape[2])
    return key_tensor, value_tensor, block_size, kv_heads, head_dim, True


def _flat_key_value(key_tensor: dict[str, Any], value_tensor: dict[str, Any], block_index: int, head_index: int, dim_index: int, token_index: int) -> tuple[float, float]:
    key_shape = key_tensor["shape"]
    value_shape = value_tensor["shape"]
    key_data = key_tensor["data"]
    value_data = value_tensor["data"]

    key_offset = (((block_index * int(key_shape[1]) + head_index) * int(key_shape[2]) + dim_index) * int(key_shape[3])) + token_index
    value_offset = (((block_index * int(value_shape[1]) + head_index) * int(value_shape[2]) + token_index) * int(value_shape[3])) + dim_index
    return key_data[key_offset], value_data[value_offset]


def _source_block_count(key_source: Any, is_flat: bool) -> int:
    if is_flat:
        return int(key_source["shape"][0])
    return len(key_source)


def _target_block_id(logical_block_index: int, target_block_ids: list[int] | None) -> int:
    if target_block_ids is None:
        return logical_block_index
    return int(target_block_ids[logical_block_index])


def _combined_target_block_count(cache: Any, layer: dict[str, Any]) -> int:
    shape = _shape_of_storage(cache)
    key_source, _value_source, block_size, kv_heads, head_dim, is_flat = _layer_block_views(layer)
    source_block_count = _source_block_count(key_source, is_flat)
    layout = _combined_layout(shape, block_size, kv_heads, head_dim)
    return source_block_count * int(layout.get("target_blocks_per_source_block") or 1)


def _allocate_target_block_ids(runtime: Any, target_block_count: int) -> tuple[list[int] | None, dict[str, Any]]:
    if os.getenv("PERMEANT_VLLM_ALLOCATE_BLOCK_POOL", "1") == "0":
        return None, {"mode": "sequential_disabled"}
    try:
        scheduler = runtime.llm.llm_engine.engine_core.engine_core.scheduler
        block_pool = scheduler.kv_cache_manager.block_pool
        blocks = block_pool.get_new_blocks(target_block_count)
        block_ids = [int(block.block_id) for block in blocks]
        return block_ids, {
            "mode": "vllm_block_pool",
            "target_block_count": target_block_count,
            "target_block_ids": block_ids,
        }
    except Exception as exc:
        return None, {
            "mode": "sequential_fallback",
            "target_block_count": target_block_count,
            "error": repr(exc),
        }


def _write_combined_cache(cache: Any, layer: dict[str, Any], target_block_ids: list[int] | None = None) -> None:
    shape = _shape_of_storage(cache)
    key_source, value_source, block_size, kv_heads, head_dim, is_flat = _layer_block_views(layer)
    source_block_count = _source_block_count(key_source, is_flat)

    if len(shape) != 5 or shape[1] != 2:
        raise RuntimeError(f"unsupported combined kv_cache shape {shape}")

    if shape[2] == block_size and shape[3] == kv_heads and shape[4] == head_dim:
        for block_index in range(source_block_count):
            for token_index in range(block_size):
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        if is_flat:
                            key_value, value_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)
                        else:
                            key_value = key_source[block_index][head_index][dim_index][token_index]
                            value_value = value_source[block_index][head_index][token_index][dim_index]
                        target_block_index = _target_block_id(block_index, target_block_ids)
                        cache[target_block_index][0][token_index][head_index][dim_index] = key_value
                        cache[target_block_index][1][token_index][head_index][dim_index] = value_value
        return

    if shape[2] == kv_heads and shape[3] == block_size and shape[4] == head_dim:
        for block_index in range(source_block_count):
            for head_index in range(kv_heads):
                for token_index in range(block_size):
                    for dim_index in range(head_dim):
                        if is_flat:
                            key_value, value_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)
                        else:
                            key_value = key_source[block_index][head_index][dim_index][token_index]
                            value_value = value_source[block_index][head_index][token_index][dim_index]
                        target_block_index = _target_block_id(block_index, target_block_ids)
                        cache[target_block_index][0][head_index][token_index][dim_index] = key_value
                        cache[target_block_index][1][head_index][token_index][dim_index] = value_value
        return

    if shape[3] == kv_heads and shape[4] == head_dim and block_size % shape[2] == 0:
        tokens_per_target_block = shape[2]
        blocks_per_source_block = block_size // tokens_per_target_block
        for block_index in range(source_block_count):
            for token_index in range(block_size):
                logical_target_block_index = block_index * blocks_per_source_block + (token_index // tokens_per_target_block)
                target_block_index = _target_block_id(logical_target_block_index, target_block_ids)
                target_token_index = token_index % tokens_per_target_block
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        if is_flat:
                            key_value, value_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)
                        else:
                            key_value = key_source[block_index][head_index][dim_index][token_index]
                            value_value = value_source[block_index][head_index][token_index][dim_index]
                        cache[target_block_index][0][target_token_index][head_index][dim_index] = key_value
                        cache[target_block_index][1][target_token_index][head_index][dim_index] = value_value
        return

    if shape[2] == kv_heads and shape[4] == head_dim and block_size % shape[3] == 0:
        tokens_per_target_block = shape[3]
        blocks_per_source_block = block_size // tokens_per_target_block
        for block_index in range(source_block_count):
            for token_index in range(block_size):
                logical_target_block_index = block_index * blocks_per_source_block + (token_index // tokens_per_target_block)
                target_block_index = _target_block_id(logical_target_block_index, target_block_ids)
                target_token_index = token_index % tokens_per_target_block
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        if is_flat:
                            key_value, value_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)
                        else:
                            key_value = key_source[block_index][head_index][dim_index][token_index]
                            value_value = value_source[block_index][head_index][token_index][dim_index]
                        cache[target_block_index][0][head_index][target_token_index][dim_index] = key_value
                        cache[target_block_index][1][head_index][target_token_index][dim_index] = value_value
        return

    raise RuntimeError(
        "unsupported combined kv_cache layout "
        f"{shape} for source block_size={block_size}, kv_heads={kv_heads}, head_dim={head_dim}"
    )


def _write_separate_cache(cache_pair: Any, layer: dict[str, Any]) -> None:
    if isinstance(cache_pair, dict):
        key_cache = cache_pair.get("key")
        value_cache = cache_pair.get("value")
    elif isinstance(cache_pair, (list, tuple)) and len(cache_pair) == 2:
        key_cache, value_cache = cache_pair
    else:
        raise RuntimeError("separate kv cache must be a 2-tuple/list or dict with key/value entries")

    if key_cache is None or value_cache is None:
        raise RuntimeError("separate kv cache pair is missing key/value storage")

    key_source, value_source, block_size, kv_heads, head_dim, is_flat = _layer_block_views(layer)

    key_shape = _shape_of_storage(key_cache)
    value_shape = _shape_of_storage(value_cache)

    if key_shape == [int(key_shape[0]), kv_heads, head_dim, block_size]:
        for block_index in range(key_shape[0]):
            for head_index in range(kv_heads):
                for dim_index in range(head_dim):
                    for token_index in range(block_size):
                        key_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)[0] if is_flat else key_source[block_index][head_index][dim_index][token_index]
                        key_cache[block_index][head_index][dim_index][token_index] = key_value
    elif key_shape == [int(key_shape[0]), block_size, kv_heads, head_dim]:
        for block_index in range(key_shape[0]):
            for token_index in range(block_size):
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        key_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)[0] if is_flat else key_source[block_index][head_index][dim_index][token_index]
                        key_cache[block_index][token_index][head_index][dim_index] = key_value
    else:
        raise RuntimeError(f"unsupported key cache layout {key_shape}")

    if value_shape == [int(value_shape[0]), kv_heads, block_size, head_dim]:
        for block_index in range(value_shape[0]):
            for head_index in range(kv_heads):
                for token_index in range(block_size):
                    for dim_index in range(head_dim):
                        value_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)[1] if is_flat else value_source[block_index][head_index][token_index][dim_index]
                        value_cache[block_index][head_index][token_index][dim_index] = value_value
    elif value_shape == [int(value_shape[0]), block_size, kv_heads, head_dim]:
        for block_index in range(value_shape[0]):
            for token_index in range(block_size):
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        value_value = _flat_key_value(key_source, value_source, block_index, head_index, dim_index, token_index)[1] if is_flat else value_source[block_index][head_index][token_index][dim_index]
                        value_cache[block_index][token_index][head_index][dim_index] = value_value
    else:
        raise RuntimeError(f"unsupported value cache layout {value_shape}")


def _direct_register_into_kv_caches(runtime: Any, payload: dict[str, Any]) -> dict[str, Any]:
    kv_caches = _get_kv_caches(runtime)
    layer_map = _get_layer_map(runtime, kv_caches)
    written_layers: list[str] = []
    written_layer_summaries: list[dict[str, Any]] = []
    target_block_ids: list[int] | None = None
    target_block_allocation: dict[str, Any] = {"mode": "not_allocated"}

    layers = payload.get("layers", [])
    if layers:
        first_layer = layers[0]
        first_layer_index = first_layer.get("layer_index") if isinstance(first_layer, dict) else None
        if isinstance(first_layer_index, int) and first_layer_index in layer_map:
            first_cache = kv_caches[layer_map[first_layer_index]]
            if len(_shape_of_storage(first_cache)) == 5:
                target_block_count = _combined_target_block_count(first_cache, first_layer)
                target_block_ids, target_block_allocation = _allocate_target_block_ids(runtime, target_block_count)

    for layer in layers:
        layer_index = layer.get("layer_index")
        if not isinstance(layer_index, int):
            raise RuntimeError("prepared payload layer_index must be an int")
        if layer_index not in layer_map:
            raise RuntimeError(f"runtime layer map is missing layer_index {layer_index}")
        layer_name = layer_map[layer_index]
        cache = kv_caches[layer_name]
        shape = _shape_of_storage(cache)
        if len(shape) == 5:
            _write_combined_cache(cache, layer, target_block_ids)
            slot_probe = _combined_slot_samples(cache, layer, target_block_ids)
        else:
            _write_separate_cache(cache, layer)
            slot_probe = {"layout": {"kind": "separate"}, "samples": [], "all_samples_match": None}
        written_layers.append(layer_name)
        written_layer_summaries.append(
            {
                "layer_index": layer_index,
                "layer_name": layer_name,
                "source": _prepared_layer_summary(layer),
                "target": _cache_storage_summary(cache),
                "slot_probe": slot_probe,
            }
        )

    return {
        "success": True,
        "written_layers": written_layers,
        "written_layer_summaries": written_layer_summaries,
        "target_block_allocation": target_block_allocation,
    }


def _direct_verify_runtime(runtime: Any, block_hashes: list[str]) -> dict[str, Any] | None:
    hashes = getattr(runtime, "registered_hashes", None)
    if isinstance(hashes, set):
        missing = [hash_value for hash_value in block_hashes if hash_value not in hashes]
    elif isinstance(hashes, list):
        missing = [hash_value for hash_value in block_hashes if hash_value not in hashes]
    else:
        return None
    if missing:
        return {"success": False, "missing_hashes": missing}
    return {"success": True}


def runtime_hook(payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = _resolve_runtime(payload, request)

    if "layers" in payload:
        method = getattr(runtime, _register_method_name(), None)
        if method is not None:
            result = _normalize_result(_invoke(method, payload, request))
        else:
            result = _direct_register_into_kv_caches(runtime, payload)
        if result.get("success"):
            hash_value = payload.get("hash")
            if isinstance(hash_value, str) and hash_value:
                _store_hash(hash_value)
                _note_runtime_hash(runtime, hash_value)
        return result

    if "block_hashes" in payload:
        method = getattr(runtime, _verify_method_name(), None)
        if method is not None:
            return _normalize_result(_invoke(method, payload, request))
        direct_result = _direct_verify_runtime(runtime, payload.get("block_hashes", []))
        if direct_result is not None:
            return direct_result
        return _verify_from_state(payload.get("block_hashes", []))

    if payload.get("action") == "export_reverse_runtime_state":
        method = getattr(runtime, _reverse_export_method_name(), None)
        if method is None:
            return {
                "success": False,
                "error": "runtime does not expose export_reverse_runtime_state",
            }
        return _normalize_result(_invoke(method, payload, request))

    raise RuntimeError("unsupported payload for live target-runtime registration")
