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
        self.last_register_payload: dict[str, Any] | None = None
        self.last_verify_result: dict[str, Any] | None = None
        self.last_continuation: dict[str, Any] | None = None

    def register_permeant_block(self, payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
        from vllm_live_runtime_registry import _direct_register_into_kv_caches

        result = dict(_direct_register_into_kv_caches(self, payload))
        self.last_register_payload = {
            "hash": payload.get("hash"),
            "layer_count": len(payload.get("layers", [])),
            "request": request or {},
        }
        _append_probe_event(
            {
                "event": "register_permeant_block",
                "hash": payload.get("hash"),
                "layer_count": len(payload.get("layers", [])),
                "written_layers": result.get("written_layers", []),
            }
        )
        return result

    def verify_permeant_hashes(self, payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
        block_hashes = payload.get("block_hashes", [])
        missing = [hash_value for hash_value in block_hashes if hash_value not in self.registered_hashes]
        if missing:
            result = {"success": False, "missing_hashes": missing}
            self.last_verify_result = result
            _append_probe_event({"event": "verify_permeant_hashes", **result})
            return result

        result: dict[str, Any] = {"success": True, "verified_hashes": list(block_hashes)}
        prompt = os.getenv("PERMEANT_VLLM_CONTINUATION_PROMPT")
        if prompt:
            continuation = self.generate_continuation(
                prompt=prompt,
                max_tokens=int(os.getenv("PERMEANT_VLLM_CONTINUATION_MAX_TOKENS", "16")),
            )
            self.last_continuation = continuation
            result["continuation"] = continuation
            source_reference = _source_continuation_reference()
            if source_reference is not None:
                result["source_comparison"] = _compare_continuations(source_reference, continuation)

        self.last_verify_result = result
        _append_probe_event(
            {
                "event": "verify_permeant_hashes",
                "request": request or {},
                "continuation_generated": "continuation" in result,
                "source_comparison_available": "source_comparison" in result,
                **{k: v for k, v in result.items() if k != "continuation"},
            }
        )
        return result

    def generate_continuation(self, prompt: str, max_tokens: int = 16) -> dict[str, Any]:
        from vllm import SamplingParams

        sampling = SamplingParams(max_tokens=max_tokens, temperature=0.0)
        outputs = self.llm.generate([prompt], sampling)
        text = ""
        token_ids: list[int] = []

        if outputs:
            first = outputs[0]
            candidates = getattr(first, "outputs", None) or []
            if candidates:
                candidate = candidates[0]
                text = getattr(candidate, "text", "") or ""
                maybe_token_ids = getattr(candidate, "token_ids", None)
                if isinstance(maybe_token_ids, list):
                    token_ids = [int(item) for item in maybe_token_ids]

        continuation = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "text": text,
            "token_ids": token_ids,
        }
        _append_probe_event({"event": "generate_continuation", **continuation})
        return continuation


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


def _append_probe_event(payload: dict[str, Any]) -> None:
    path = _probe_file()
    if path is None:
        return
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = {}
    events = existing.get("events")
    if not isinstance(events, list):
        events = []
    events.append(payload)
    existing["events"] = events
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2))


def _source_continuation_reference() -> dict[str, Any] | None:
    value = os.getenv("PERMEANT_SOURCE_CONTINUATION_FILE")
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _compare_continuations(reference: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_text = reference.get("text")
    expected_token_ids = reference.get("token_ids")
    actual_text = actual.get("text")
    actual_token_ids = actual.get("token_ids")

    text_matches = isinstance(expected_text, str) and expected_text == actual_text
    token_ids_match = isinstance(expected_token_ids, list) and expected_token_ids == actual_token_ids

    first_token_mismatch_index = None
    if isinstance(expected_token_ids, list) and isinstance(actual_token_ids, list):
        max_len = min(len(expected_token_ids), len(actual_token_ids))
        for index in range(max_len):
            if expected_token_ids[index] != actual_token_ids[index]:
                first_token_mismatch_index = index
                break
        if first_token_mismatch_index is None and len(expected_token_ids) != len(actual_token_ids):
            first_token_mismatch_index = max_len

    return {
        "reference_available": True,
        "prompt_matches": reference.get("prompt") == actual.get("prompt"),
        "text_matches": text_matches,
        "token_ids_match": token_ids_match,
        "matches": text_matches and token_ids_match,
        "expected_text": expected_text,
        "actual_text": actual_text,
        "expected_token_ids": expected_token_ids,
        "actual_token_ids": actual_token_ids,
        "first_token_mismatch_index": first_token_mismatch_index,
    }


def _looks_like_cache_storage(value: Any) -> bool:
    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            dims = [int(item) for item in shape]
        except Exception:
            dims = []
        if 4 <= len(dims) <= 5:
            return True

    if isinstance(value, dict):
        keys = set(value)
        if {"key", "value"}.issubset(keys):
            return True

    if isinstance(value, (list, tuple)) and len(value) == 2:
        first_shape = getattr(value[0], "shape", None)
        second_shape = getattr(value[1], "shape", None)
        if first_shape is not None and second_shape is not None:
            return True

    return False


def _merge_cache_mapping(kv_caches: dict[str, Any], value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    added = False
    for key, cache_value in value.items():
        if not isinstance(key, str):
            continue
        if _looks_like_cache_storage(cache_value):
            kv_caches.setdefault(key, cache_value)
            added = True
    return added


def _find_kv_caches(root: Any) -> tuple[dict[str, Any], dict[int, str]]:
    seen: set[int] = set()
    kv_caches: dict[str, Any] = {}

    def walk(obj: Any, path: str, depth: int) -> None:
        if obj is None or depth > 12:
            return
        obj_id = id(obj)
        if obj_id in seen:
            return
        seen.add(obj_id)

        if _looks_like_cache_storage(obj):
            kv_caches.setdefault(path, obj)

        if _merge_cache_mapping(kv_caches, obj):
            return

        for attr_name in ("kv_cache", "kv_caches", "device_kv_caches"):
            if not hasattr(obj, attr_name):
                continue
            cache = getattr(obj, attr_name)
            if cache is None:
                continue
            if _looks_like_cache_storage(cache):
                attr_path = f"{path}.{attr_name}" if path else attr_name
                kv_caches.setdefault(attr_path, cache)
            if _merge_cache_mapping(kv_caches, cache):
                return

        if hasattr(obj, "__dict__"):
            for name, value in vars(obj).items():
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
    preferred_paths = [
        path for path in sorted(kv_caches) if ".layers." in path and ".kv_cache" in path
    ]
    for path in preferred_paths + sorted(kv_caches):
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
        preferred_keys = [
            key for key in sorted(kv_caches.keys()) if ".layers." in key and ".kv_cache" in key
        ]
        metadata = {
            "model": os.getenv("PERMEANT_VLLM_MODEL"),
            "layer_count": len(layer_map),
            "kv_cache_keys": (preferred_keys or list(sorted(kv_caches.keys())))[:16],
        }
        _RUNTIME_SINGLETON = RealVllmRuntime(llm=llm, kv_caches=kv_caches, layer_map=layer_map, metadata=metadata)
        _write_probe({"event": "runtime_initialized", **metadata})
    return _RUNTIME_SINGLETON
