"""Helpers for turning a live MLX cache object into PermeantOS extractor JSON."""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_adapter_utils import AdapterError, load_hook, normalize_extractor_payload

KEY_FIELDS = ("key", "keys", "k", "k_cache")
VALUE_FIELDS = ("value", "values", "v", "v_cache")


def _to_builtin(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, tuple):
        return [_to_builtin(item) for item in value]
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    return value


def _shape_of(value: Any) -> list[int]:
    shape: list[int] = []
    cursor = value
    while isinstance(cursor, list):
        shape.append(len(cursor))
        cursor = cursor[0] if cursor else []
    return shape


def _transpose_0_1(tensor: list[list[list[float]]]) -> list[list[list[float]]]:
    first = len(tensor)
    second = len(tensor[0]) if tensor else 0
    return [[tensor[i][j] for i in range(first)] for j in range(second)]



def _trim_seq_len(tensor: list[Any], seq_len: int | None) -> list[Any]:
    if seq_len is None:
        return tensor
    return tensor[:seq_len]



def _canonicalize_tensor(name: str, tensor: Any, seq_len: int | None) -> list[Any]:
    data = _to_builtin(tensor)
    shape = _shape_of(data)

    if len(shape) == 4 and shape[0] == 1:
        data = data[0]
        shape = _shape_of(data)

    if len(shape) != 3:
        raise AdapterError(
            f"{name} must normalize to a 3D tensor [seq, kv_heads, head_dim]; got shape {shape}"
        )

    if (
        seq_len is not None
        and len(shape) == 3
        and shape[0] != seq_len
        and (
            shape[1] == seq_len
            or (shape[0] < shape[1] and shape[1] >= seq_len)
        )
    ):
        data = _transpose_0_1(data)
        shape = _shape_of(data)

    if seq_len is not None and shape[0] < seq_len:
        raise AdapterError(f"{name} only contains {shape[0]} positions but seq_len={seq_len}")

    return _trim_seq_len(data, seq_len)



def _lookup_named_field(container: Any, candidates: Iterable[str]) -> Any:
    if isinstance(container, dict):
        for name in candidates:
            if name in container:
                return container[name]
    for name in candidates:
        if hasattr(container, name):
            return getattr(container, name)
    return None



def _layer_pair(layer: Any, index: int) -> tuple[Any, Any]:
    if isinstance(layer, (tuple, list)) and len(layer) == 2:
        return layer[0], layer[1]

    key = _lookup_named_field(layer, KEY_FIELDS)
    value = _lookup_named_field(layer, VALUE_FIELDS)
    if key is None or value is None:
        raise AdapterError(
            f"layer {index} does not expose a recognizable key/value pair; "
            "expected dict/object fields like 'key' and 'value'"
        )
    return key, value



def extract_cache_layers(cache: Any) -> list[tuple[Any, Any]]:
    candidate = cache
    if isinstance(cache, dict):
        for key in ("layers", "kv_cache", "cache", "entries"):
            if key in cache:
                candidate = cache[key]
                break

    if not isinstance(candidate, (list, tuple)):
        raise AdapterError("MLX cache provider must return a layer list/tuple or a dict containing one")

    return [_layer_pair(layer, index) for index, layer in enumerate(candidate)]



def _call_provider(provider: Callable[..., Any], request: dict[str, Any]) -> Any:
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError):
        return provider(request)

    positional = [
        p
        for p in signature.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if not positional:
        return provider()
    return provider(request)



def load_cache_from_provider_env(request: dict[str, Any]) -> Any:
    provider_spec = os.getenv("PERMEANT_MLX_CACHE_PROVIDER")
    if not provider_spec:
        raise AdapterError(
            "PERMEANT_MLX_CACHE_PROVIDER is not set. Point it at a callable that returns the live MLX KV cache."
        )
    provider = load_hook(provider_spec)
    return _call_provider(provider, request)



def build_extractor_response_from_cache(
    cache: Any,
    *,
    seq_len: int | None = None,
    required_tensor_names: list[str] | None = None,
) -> dict[str, Any]:
    layers = extract_cache_layers(cache)
    tensors: list[dict[str, Any]] = []

    for layer_index, (key_tensor, value_tensor) in enumerate(layers):
        tensors.append(
            {
                "name": f"layer.{layer_index}.key",
                "shape": _shape_of(_canonicalize_tensor("key", key_tensor, seq_len)),
                "data": _canonicalize_tensor("key", key_tensor, seq_len),
            }
        )
        tensors.append(
            {
                "name": f"layer.{layer_index}.value",
                "shape": _shape_of(_canonicalize_tensor("value", value_tensor, seq_len)),
                "data": _canonicalize_tensor("value", value_tensor, seq_len),
            }
        )

    normalized = normalize_extractor_payload({"tensors": tensors})
    if required_tensor_names:
        tensor_map = {tensor["name"]: tensor for tensor in normalized["tensors"]}
        missing = [name for name in required_tensor_names if name not in tensor_map]
        if missing:
            raise AdapterError(f"MLX cache provider did not yield required tensors: {missing}")
        normalized = {"tensors": [tensor_map[name] for name in required_tensor_names]}
    return normalized
