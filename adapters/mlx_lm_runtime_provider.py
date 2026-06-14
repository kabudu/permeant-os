"""Source-side provider aimed at common MLX / mlx_lm process layouts.

Environment:
- PERMEANT_MLX_RUNTIME_MODULE: import path for the live process module
- PERMEANT_MLX_RUNTIME_OBJECT: object or callable name inside that module

Optional:
- PERMEANT_MLX_RUNTIME_CALL=1: call the resolved object to obtain a runtime/session
- PERMEANT_MLX_RUNTIME_CACHE_PATH: comma-separated candidate attribute paths

The resolved cache object may be:
- a layer list directly
- an object exposing `.layers`
- a dict containing `layers`, `cache`, `kv_cache`, or `prompt_cache`
"""

from __future__ import annotations

import importlib
import inspect
import os
from typing import Any, Iterable

from runtime_adapter_utils import AdapterError


DEFAULT_CACHE_PATHS = (
    "kv_cache",
    "prompt_cache",
    "cache",
    "state.kv_cache",
    "state.prompt_cache",
    "state.cache",
    "session.kv_cache",
    "session.prompt_cache",
    "session.cache",
    "generator.kv_cache",
    "generator.prompt_cache",
    "generator.cache",
)

DEFAULT_OBJECT_NAMES = (
    "runtime",
    "session",
    "generator",
    "engine",
    "model",
    "app",
)


def _attribute_paths() -> tuple[str, ...]:
    value = os.getenv("PERMEANT_MLX_RUNTIME_CACHE_PATH")
    if not value:
        return DEFAULT_CACHE_PATHS
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(parts) if parts else DEFAULT_CACHE_PATHS


def _object_names() -> tuple[str, ...]:
    value = os.getenv("PERMEANT_MLX_RUNTIME_OBJECTS")
    if not value:
        return DEFAULT_OBJECT_NAMES
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(parts) if parts else DEFAULT_OBJECT_NAMES


def _dig(container: Any, path: str) -> Any:
    cursor = container
    for segment in path.split("."):
        if isinstance(cursor, dict):
            if segment not in cursor:
                return None
            cursor = cursor[segment]
            continue
        if not hasattr(cursor, segment):
            return None
        cursor = getattr(cursor, segment)
    return cursor


def _call_if_needed(value: Any, request: dict[str, Any] | None) -> Any:
    if not callable(value):
        return value
    if os.getenv("PERMEANT_MLX_RUNTIME_CALL", "").lower() not in {"1", "true", "yes"}:
        return value
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return value(request) if request is not None else value()
    positional = [
        param
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if not positional:
        return value()
    return value(request) if request is not None else value()


def _normalize_cache_root(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("layers", "cache", "kv_cache", "prompt_cache"):
            if key in value:
                return value[key]
    if hasattr(value, "layers"):
        return getattr(value, "layers")
    return value


def _resolve_candidates(runtime: Any, paths: Iterable[str]) -> Any:
    for path in paths:
        candidate = _dig(runtime, path)
        if candidate is not None:
            return _normalize_cache_root(candidate)
    return _normalize_cache_root(runtime)


def get_live_cache(request: dict[str, Any] | None = None) -> Any:
    module_name = os.getenv("PERMEANT_MLX_RUNTIME_MODULE")
    object_name = os.getenv("PERMEANT_MLX_RUNTIME_OBJECT")
    if not module_name:
        raise AdapterError("Set PERMEANT_MLX_RUNTIME_MODULE for mlx_lm runtime export")

    module = importlib.import_module(module_name)
    candidate_names = (object_name,) if object_name else _object_names()
    runtime = None
    resolved_name = None
    for candidate_name in candidate_names:
        runtime = getattr(module, candidate_name, None)
        if runtime is not None:
            resolved_name = candidate_name
            break
    if runtime is None:
        raise AdapterError(
            f"none of the runtime objects {candidate_names} were found in module '{module_name}'"
        )

    runtime = _call_if_needed(runtime, request)
    cache = _resolve_candidates(runtime, _attribute_paths())

    if isinstance(cache, (list, tuple)):
        return cache
    if hasattr(cache, "layers"):
        return getattr(cache, "layers")
    if isinstance(cache, dict):
        for key in ("layers", "cache", "kv_cache", "prompt_cache"):
            if key in cache:
                return cache[key]

    raise AdapterError(
        f"Unable to resolve a usable MLX cache object from '{resolved_name}'. "
        "Set PERMEANT_MLX_RUNTIME_CACHE_PATH to the attribute path that exposes the live cache."
    )
