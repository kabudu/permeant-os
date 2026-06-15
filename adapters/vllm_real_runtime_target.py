"""Real vLLM runtime target helper for long-lived import-worker processes.

This module is designed to run on the target host inside the same Python
process as `vllm_import_worker.py`. It lazily creates a real `vllm.LLM`
instance backed by a small local model, warms it once, discovers live
per-layer KV cache tensors, and exposes a runtime object compatible with
`vllm_live_runtime_registry.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_RUNTIME_SINGLETON = None


class RealVllmRuntime:
    def __init__(self, llm: Any, kv_caches: dict[str, Any], layer_map: dict[int, str], metadata: dict[str, Any]) -> None:
        self.llm = llm
        self.kv_caches = kv_caches
        self.permeant_layer_map = layer_map
        self.registered_hashes: set[str] = set()
        self.metadata = metadata


def _probe_file() -> Path | None:
    value = os.getenv("PERMEANT_VLLM_RUNTIME_PROBE_FILE")
    if not value:
        return None
    return Path(value).expanduser()


def _write_probe(payload: dict[str, Any]) -> None:
    path = _probe_file()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _find_kv_caches(root: Any) -> tuple[dict[str, Any], dict[int, str]]:
    seen: set[int] = set()
    kv_caches: dict[str, Any] = {}

    def walk(obj: Any, path: str, depth: int) -> None:
        if obj is None or depth > 8:
            return
        obj_id = id(obj)
        if obj_id in seen:
            return
        seen.add(obj_id)

        if hasattr(obj, "kv_cache"):
            cache = getattr(obj, "kv_cache")
            if cache is not None:
                kv_caches[path] = cache

        if hasattr(obj, "__dict__"):
            for name, value in vars(obj).items():
                if name.startswith("_"):
                    continue
                walk(value, f"{path}.{name}" if path else name, depth + 1)

        if isinstance(obj, dict):
            for name, value in obj.items():
                if isinstance(name, str):
                    walk(value, f"{path}.{name}" if path else name, depth + 1)

        if isinstance(obj, (list, tuple)):
            for index, value in enumerate(obj):
                walk(value, f"{path}.{index}" if path else str(index), depth + 1)

    walk(root, "runtime", 0)

    layer_map: dict[int, str] = {}
    for path in sorted(kv_caches):
        if ".layers." in path:
            try:
                after = path.split(".layers.", 1)[1]
                layer_index = int(after.split(".", 1)[0])
            except Exception:
                continue
            layer_map.setdefault(layer_index, path)

    if not kv_caches:
        raise RuntimeError("could not discover live kv_cache tensors in the vLLM runtime object")
    if not layer_map:
        raise RuntimeError("could not infer a layer map from the live vLLM runtime object")
    return kv_caches, layer_map


def _create_llm() -> Any:
    from vllm import LLM, SamplingParams

    model_path = os.getenv("PERMEANT_VLLM_MODEL")
    if not model_path:
        raise RuntimeError("set PERMEANT_VLLM_MODEL to a local model path for the real vLLM runtime target")

    gpu_memory_utilization = float(os.getenv("PERMEANT_VLLM_GPU_MEMORY_UTILIZATION", "0.4"))
    max_model_len = int(os.getenv("PERMEANT_VLLM_MAX_MODEL_LEN", "2048"))

    llm = LLM(
        model=model_path,
        enforce_eager=True,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
        trust_remote_code=False,
    )
    llm.generate(["hello"], SamplingParams(max_tokens=1, temperature=0.0))
    return llm


def get_runtime(payload: dict[str, Any] | None = None, request: dict[str, Any] | None = None) -> RealVllmRuntime:
    global _RUNTIME_SINGLETON

    if _RUNTIME_SINGLETON is None:
        llm = _create_llm()
        kv_caches, layer_map = _find_kv_caches(llm)
        metadata = {
            "model": os.getenv("PERMEANT_VLLM_MODEL"),
            "layer_count": len(layer_map),
            "kv_cache_keys": list(sorted(kv_caches.keys()))[:16],
        }
        _RUNTIME_SINGLETON = RealVllmRuntime(llm=llm, kv_caches=kv_caches, layer_map=layer_map, metadata=metadata)
        _write_probe({"event": "runtime_initialized", **metadata})
    return _RUNTIME_SINGLETON
