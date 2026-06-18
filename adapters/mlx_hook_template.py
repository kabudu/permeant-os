"""Usable live extractor hook for PERMEANT_EXTRACTOR_HOOK.

Environment:
- PERMEANT_MLX_CACHE_PROVIDER: required module/file hook returning the live KV cache object
- PERMEANT_MLX_CACHE_JSON: optional shortcut to a canonical extractor JSON file

The provider callable may accept either zero arguments or the extractor request object.
It should return one of:
- a list/tuple of per-layer `(key, value)` pairs
- a list/tuple of dict/object layers exposing `key`/`value`
- a dict containing that list under `layers`, `kv_cache`, `cache`, or `entries`
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mlx_runtime_bridge import build_extractor_response_from_cache, load_cache_from_provider_env
from runtime_adapter_utils import load_json_file, normalize_extractor_payload


def extractor_hook(request: dict[str, Any]) -> dict[str, Any]:
    fixture_path = os.getenv("PERMEANT_MLX_CACHE_JSON")
    if fixture_path:
        return normalize_extractor_payload(load_json_file(fixture_path))

    cache = load_cache_from_provider_env(request)
    return build_extractor_response_from_cache(
        cache,
        seq_len=request.get("seq_len"),
        required_tensor_names=request.get("tensor_names"),
    )
