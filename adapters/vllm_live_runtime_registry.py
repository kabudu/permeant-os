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


def _write_combined_cache(cache: Any, layer: dict[str, Any]) -> None:
    shape = _shape_of_storage(cache)
    key_blocks = layer["key_blocks"]
    value_blocks = layer["value_blocks"]
    block_size = len(value_blocks[0][0]) if value_blocks and value_blocks[0] else 0
    kv_heads = len(key_blocks[0]) if key_blocks else 0
    head_dim = len(key_blocks[0][0]) if key_blocks and key_blocks[0] else 0

    if len(shape) != 5 or shape[1] != 2:
        raise RuntimeError(f"unsupported combined kv_cache shape {shape}")

    if shape[2] == block_size and shape[3] == kv_heads and shape[4] == head_dim:
        for block_index in range(len(key_blocks)):
            for token_index in range(block_size):
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        cache[block_index][0][token_index][head_index][dim_index] = key_blocks[block_index][head_index][dim_index][token_index]
                        cache[block_index][1][token_index][head_index][dim_index] = value_blocks[block_index][head_index][token_index][dim_index]
        return

    if shape[2] == kv_heads and shape[3] == block_size and shape[4] == head_dim:
        for block_index in range(len(key_blocks)):
            for head_index in range(kv_heads):
                for token_index in range(block_size):
                    for dim_index in range(head_dim):
                        cache[block_index][0][head_index][token_index][dim_index] = key_blocks[block_index][head_index][dim_index][token_index]
                        cache[block_index][1][head_index][token_index][dim_index] = value_blocks[block_index][head_index][token_index][dim_index]
        return

    raise RuntimeError(f"unsupported combined kv_cache layout {shape}")


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

    key_blocks = layer["key_blocks"]
    value_blocks = layer["value_blocks"]
    block_size = len(value_blocks[0][0]) if value_blocks and value_blocks[0] else 0
    kv_heads = len(key_blocks[0]) if key_blocks else 0
    head_dim = len(key_blocks[0][0]) if key_blocks and key_blocks[0] else 0

    key_shape = _shape_of_storage(key_cache)
    value_shape = _shape_of_storage(value_cache)

    if key_shape == [len(key_blocks), kv_heads, head_dim, block_size]:
        for block_index in range(len(key_blocks)):
            for head_index in range(kv_heads):
                for dim_index in range(head_dim):
                    for token_index in range(block_size):
                        key_cache[block_index][head_index][dim_index][token_index] = key_blocks[block_index][head_index][dim_index][token_index]
    elif key_shape == [len(key_blocks), block_size, kv_heads, head_dim]:
        for block_index in range(len(key_blocks)):
            for token_index in range(block_size):
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        key_cache[block_index][token_index][head_index][dim_index] = key_blocks[block_index][head_index][dim_index][token_index]
    else:
        raise RuntimeError(f"unsupported key cache layout {key_shape}")

    if value_shape == [len(value_blocks), kv_heads, block_size, head_dim]:
        for block_index in range(len(value_blocks)):
            for head_index in range(kv_heads):
                for token_index in range(block_size):
                    for dim_index in range(head_dim):
                        value_cache[block_index][head_index][token_index][dim_index] = value_blocks[block_index][head_index][token_index][dim_index]
    elif value_shape == [len(value_blocks), block_size, kv_heads, head_dim]:
        for block_index in range(len(value_blocks)):
            for token_index in range(block_size):
                for head_index in range(kv_heads):
                    for dim_index in range(head_dim):
                        value_cache[block_index][token_index][head_index][dim_index] = value_blocks[block_index][head_index][token_index][dim_index]
    else:
        raise RuntimeError(f"unsupported value cache layout {value_shape}")


def _direct_register_into_kv_caches(runtime: Any, payload: dict[str, Any]) -> dict[str, Any]:
    kv_caches = _get_kv_caches(runtime)
    layer_map = _get_layer_map(runtime, kv_caches)
    written_layers: list[str] = []

    for layer in payload.get("layers", []):
        layer_index = layer.get("layer_index")
        if not isinstance(layer_index, int):
            raise RuntimeError("prepared payload layer_index must be an int")
        if layer_index not in layer_map:
            raise RuntimeError(f"runtime layer map is missing layer_index {layer_index}")
        layer_name = layer_map[layer_index]
        cache = kv_caches[layer_name]
        shape = _shape_of_storage(cache)
        if len(shape) == 5:
            _write_combined_cache(cache, layer)
        else:
            _write_separate_cache(cache, layer)
        written_layers.append(layer_name)

    return {"success": True, "written_layers": written_layers}


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

    raise RuntimeError("unsupported payload for live target-runtime registration")
