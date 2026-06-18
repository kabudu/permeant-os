"""Example source-side provider for a live MLX process.

Set:
- PERMEANT_MLX_RUNTIME_MODULE=package.module
- PERMEANT_MLX_RUNTIME_OBJECT=global_name

Optional:
- PERMEANT_MLX_RUNTIME_CACHE_ATTR=kv_cache
- PERMEANT_MLX_RUNTIME_LAYERS_ATTR=layers
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from runtime_adapter_utils import AdapterError


def get_live_cache(request: dict[str, Any] | None = None) -> Any:
    module_name = os.getenv("PERMEANT_MLX_RUNTIME_MODULE")
    object_name = os.getenv("PERMEANT_MLX_RUNTIME_OBJECT")
    cache_attr = os.getenv("PERMEANT_MLX_RUNTIME_CACHE_ATTR", "kv_cache")
    layers_attr = os.getenv("PERMEANT_MLX_RUNTIME_LAYERS_ATTR", "layers")

    if not module_name or not object_name:
        raise AdapterError(
            "Set PERMEANT_MLX_RUNTIME_MODULE and PERMEANT_MLX_RUNTIME_OBJECT for the example provider"
        )

    module = importlib.import_module(module_name)
    runtime = getattr(module, object_name, None)
    if runtime is None:
        raise AdapterError(f"runtime object '{object_name}' was not found in module '{module_name}'")

    cache = getattr(runtime, cache_attr, None)
    if cache is None:
        raise AdapterError(f"runtime object '{object_name}' does not expose cache attribute '{cache_attr}'")

    layers = getattr(cache, layers_attr, None)
    if layers is not None:
        return layers
    return cache
