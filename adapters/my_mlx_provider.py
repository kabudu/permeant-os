"""Concrete scaffold for a real MLX laptop runtime.

Use this with:
- PERMEANT_MLX_EXPORTER_HOOK="/ABS/PATH/adapters/my_mlx_provider.py:provider"

This file is intentionally explicit rather than clever. Replace the placeholder
`get_live_runtime()` implementation with the exact way your MLX host process
exposes its active model/session/cache.
"""

from __future__ import annotations

from typing import Any

from mlx_runtime_bridge import build_extractor_response_from_cache


def get_live_runtime() -> Any:
    """Return the live runtime/session object from your MLX host process.

    Replace this stub with your real integration point.

    Common shapes:
    - a global singleton runtime object
    - a chat/session object holding the active prompt cache
    - a wrapper exposing `kv_cache`, `cache`, or `prompt_cache`
    """
    raise RuntimeError(
        "Implement get_live_runtime() in adapters/my_mlx_provider.py for your laptop MLX process"
    )


def extract_cache_object(runtime: Any) -> Any:
    """Return the raw cache object from the live runtime.

    Adjust the attribute selection to match your actual MLX host.
    """
    for attr in ("kv_cache", "prompt_cache", "cache"):
        if hasattr(runtime, attr):
            return getattr(runtime, attr)
    if isinstance(runtime, dict):
        for key in ("kv_cache", "prompt_cache", "cache", "layers"):
            if key in runtime:
                return runtime[key]
    return runtime


def provider(request: dict[str, Any]) -> dict[str, Any]:
    """HTTP exporter hook returning canonical extractor JSON."""
    runtime = get_live_runtime()
    cache = extract_cache_object(runtime)
    return build_extractor_response_from_cache(
        cache,
        seq_len=request.get("seq_len"),
        required_tensor_names=request.get("tensor_names"),
    )
