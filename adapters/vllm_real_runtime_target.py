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
import hashlib
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
        self.baseline_continuation: dict[str, Any] | None = None
        self.last_decode_attachment_snapshot: dict[str, Any] | None = None
        self.last_migrated_decode_attachment_attempt: dict[str, Any] | None = None

    def register_permeant_block(self, payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
        from vllm_live_runtime_registry import _direct_register_into_kv_caches

        result = dict(_direct_register_into_kv_caches(self, payload))
        layer_shapes: list[dict[str, Any]] = []
        for summary in result.get("written_layer_summaries", []):
            if not isinstance(summary, dict):
                continue
            source = summary.get("source") if isinstance(summary.get("source"), dict) else {}
            layer_shapes.append(
                {
                    "layer_index": summary.get("layer_index"),
                    "key_shape": source.get("key_shape"),
                    "value_shape": source.get("value_shape"),
                    "block_count": source.get("block_count"),
                    "block_size": source.get("block_size"),
                }
            )
        self.last_register_payload = {
            "hash": payload.get("hash"),
            "block_size": payload.get("block_size"),
            "layer_count": len(payload.get("layers", [])),
            "layer_shapes": layer_shapes,
            "target_block_allocation": result.get("target_block_allocation", {}),
            "written_layers": result.get("written_layers", []),
            "written_layer_summaries": result.get("written_layer_summaries", []),
            "request": request or {},
        }
        _append_probe_event(
            {
                "event": "register_permeant_block",
                "hash": payload.get("hash"),
                "layer_count": len(payload.get("layers", [])),
                "written_layers": result.get("written_layers", []),
                "written_layer_summaries": result.get("written_layer_summaries", []),
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
        source_reference = _source_continuation_reference()
        prompt = os.getenv("PERMEANT_VLLM_CONTINUATION_PROMPT")
        if os.getenv("PERMEANT_VLLM_CONTINUATION_PROMPT_FROM_SOURCE", "0") == "1":
            prompt = (source_reference or {}).get("prompt") or prompt
        if prompt:
            continuation = self.generate_continuation(
                prompt=prompt,
                max_tokens=int(os.getenv("PERMEANT_VLLM_CONTINUATION_MAX_TOKENS", "16")),
            )
            self.last_continuation = continuation
            result["continuation"] = continuation
            if source_reference is not None:
                result["source_comparison"] = _compare_continuations(source_reference, continuation)
            if self.baseline_continuation is not None:
                result["baseline_comparison"] = _compare_continuations(
                    self.baseline_continuation, continuation
                )
            _maybe_write_reverse_runtime_export(self, result)

        self.last_verify_result = result
        _append_probe_event(
            {
                "event": "verify_permeant_hashes",
                "request": request or {},
                "continuation_generated": "continuation" in result,
                "source_comparison_available": "source_comparison" in result,
                "baseline_comparison_available": "baseline_comparison" in result,
                **{k: v for k, v in result.items() if k != "continuation"},
            }
        )
        return result

    def generate_continuation(self, prompt: str, max_tokens: int = 16) -> dict[str, Any]:
        return self._sample_continuation(
            prompt=prompt,
            max_tokens=max_tokens,
            event_name="generate_continuation",
        )

    def export_reverse_runtime_state(
        self,
        payload: dict[str, Any] | None = None,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del payload, request
        if self.last_continuation is None:
            return {
                "success": False,
                "error": "no target continuation is available to export",
            }
        state = _build_reverse_runtime_state(self, self.last_continuation, self.last_verify_result or {})
        _append_probe_event(
            {
                "event": "reverse_runtime_state_export_api",
                "proof_hash": state.get("proof_hash"),
                "generated_token_count": state.get("generated_token_count"),
            }
        )
        return {"success": True, "reverse_runtime_state": state, **state}

    def _sample_continuation(
        self,
        prompt: str,
        max_tokens: int = 16,
        event_name: str = "generate_continuation",
    ) -> dict[str, Any]:
        from vllm import SamplingParams

        sampling = SamplingParams(max_tokens=max_tokens, temperature=0.0)
        attachment_attempt = None
        if event_name == "generate_continuation":
            attachment_attempt = _migrated_decode_attachment_attempt(self, prompt)
        before_snapshot = _decode_attachment_snapshot(
            runtime=self,
            prompt=prompt,
            stage=f"{event_name}:before_generate",
        )
        outputs = self.llm.generate([prompt], sampling)
        after_snapshot = _decode_attachment_snapshot(
            runtime=self,
            prompt=prompt,
            stage=f"{event_name}:after_generate",
            outputs=outputs,
        )
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
            "decode_attachment": {
                "attachment_attempt": attachment_attempt,
                "before": before_snapshot,
                "after": after_snapshot,
            },
        }
        self.last_decode_attachment_snapshot = after_snapshot
        _append_probe_event({"event": event_name, **continuation})
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


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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


def _reverse_runtime_export_file() -> Path | None:
    value = os.getenv("PERMEANT_VLLM_REVERSE_EXPORT_FILE")
    if not value:
        return None
    return Path(value).expanduser()


def _maybe_write_reverse_runtime_export(runtime: RealVllmRuntime, verify_result: dict[str, Any]) -> None:
    path = _reverse_runtime_export_file()
    if path is None:
        return

    continuation = verify_result.get("continuation")
    if not isinstance(continuation, dict):
        return
    payload = _build_reverse_runtime_state(runtime, continuation, verify_result)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _append_probe_event(
        {
            "event": "reverse_runtime_state_exported",
            "path": str(path),
            "proof_hash": payload["proof_hash"],
            "generated_token_count": payload["generated_token_count"],
        }
    )


def _build_reverse_runtime_state(
    runtime: RealVllmRuntime,
    continuation: dict[str, Any],
    verify_result: dict[str, Any],
) -> dict[str, Any]:
    prompt = continuation.get("prompt")
    generated_text = continuation.get("text")
    generated_token_ids = continuation.get("token_ids")
    if not isinstance(prompt, str) or not isinstance(generated_text, str):
        raise RuntimeError("target continuation is missing prompt or generated text")
    if not isinstance(generated_token_ids, list):
        generated_token_ids = []

    tokenization = _tokenize_prompt(runtime.llm, prompt)
    payload: dict[str, Any] = {
        "schema_version": "permeantos-vllm-reverse-runtime-state-v0",
        "status": "target_runtime_state_exported",
        "target_runtime": "vllm",
        "model_id": os.getenv("PERMEANT_VLLM_MODEL"),
        "prompt": prompt,
        "prompt_token_ids": tokenization.get("token_ids") if isinstance(tokenization, dict) else None,
        "prompt_token_count": tokenization.get("token_count") if isinstance(tokenization, dict) else None,
        "generated_text": generated_text,
        "generated_token_ids": [int(item) for item in generated_token_ids],
        "generated_token_count": len(generated_token_ids),
        "advanced_prompt": prompt + generated_text,
        "max_tokens": continuation.get("max_tokens"),
        "registered_hashes": sorted(runtime.registered_hashes),
        "last_registered_hash": (runtime.last_register_payload or {}).get("hash"),
        "source_comparison": verify_result.get("source_comparison"),
        "baseline_comparison": verify_result.get("baseline_comparison"),
        "decode_attachment": continuation.get("decode_attachment"),
    }
    payload["proof_hash"] = _sha256_json(
        {
            "schema_version": payload["schema_version"],
            "prompt_token_ids": payload["prompt_token_ids"],
            "generated_token_ids": payload["generated_token_ids"],
            "last_registered_hash": payload["last_registered_hash"],
            "registered_hashes": payload["registered_hashes"],
        }
    )
    return payload


def _compare_continuations(reference: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_text = reference.get("text")
    expected_token_ids = reference.get("token_ids")
    actual_text = actual.get("text")
    actual_token_ids = actual.get("token_ids")

    text_matches = isinstance(expected_text, str) and expected_text == actual_text
    token_ids_match = isinstance(expected_token_ids, list) and expected_token_ids == actual_token_ids

    first_token_mismatch_index = None
    shared_prefix_token_count = None
    actual_ended_before_reference = False
    reference_ended_before_actual = False
    if isinstance(expected_token_ids, list) and isinstance(actual_token_ids, list):
        max_len = min(len(expected_token_ids), len(actual_token_ids))
        shared_prefix_token_count = max_len
        for index in range(max_len):
            if expected_token_ids[index] != actual_token_ids[index]:
                first_token_mismatch_index = index
                shared_prefix_token_count = index
                break
        if first_token_mismatch_index is None and len(expected_token_ids) != len(actual_token_ids):
            first_token_mismatch_index = max_len
            actual_ended_before_reference = len(actual_token_ids) < len(expected_token_ids)
            reference_ended_before_actual = len(expected_token_ids) < len(actual_token_ids)

    return {
        "reference_available": True,
        "prompt_matches": reference.get("prompt") == actual.get("prompt"),
        "text_matches": text_matches,
        "token_ids_match": token_ids_match,
        "shared_prefix_token_count": shared_prefix_token_count,
        "expected_token_count": len(expected_token_ids) if isinstance(expected_token_ids, list) else None,
        "actual_token_count": len(actual_token_ids) if isinstance(actual_token_ids, list) else None,
        "actual_ended_before_reference": actual_ended_before_reference,
        "reference_ended_before_actual": reference_ended_before_actual,
        "matches": text_matches and token_ids_match,
        "expected_text": expected_text,
        "actual_text": actual_text,
        "expected_token_ids": expected_token_ids,
        "actual_token_ids": actual_token_ids,
        "first_token_mismatch_index": first_token_mismatch_index,
    }


def _safe_type_name(value: Any) -> str:
    try:
        return f"{type(value).__module__}.{type(value).__qualname__}"
    except Exception:
        return type(value).__name__


def _safe_len(value: Any) -> int | None:
    try:
        return len(value)
    except Exception:
        return None


def _json_safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            scalar = value.item()
            if isinstance(scalar, (str, int, float, bool)):
                return scalar
        except Exception:
            pass
    return None


def _summarize_value(value: Any, depth: int = 0) -> Any:
    scalar = _json_safe_scalar(value)
    if scalar is not None or value is None:
        return scalar

    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            return {"type": _safe_type_name(value), "shape": [int(item) for item in shape]}
        except Exception:
            return {"type": _safe_type_name(value), "shape": str(shape)}

    if isinstance(value, dict):
        if depth >= 1:
            return {"type": "dict", "len": len(value), "keys": [str(key) for key in list(value.keys())[:8]]}
        return {
            str(key): _summarize_value(item, depth + 1)
            for key, item in list(value.items())[:12]
            if isinstance(key, (str, int, float, bool))
        }

    if isinstance(value, (list, tuple)):
        if depth >= 1:
            return {"type": type(value).__name__, "len": len(value)}
        return [_summarize_value(item, depth + 1) for item in list(value)[:8]]

    length = _safe_len(value)
    summary: dict[str, Any] = {"type": _safe_type_name(value)}
    if length is not None:
        summary["len"] = length
    return summary


def _interesting_attr_name(name: str) -> bool:
    lowered = name.lower()
    needles = (
        "block",
        "cache",
        "decode",
        "engine",
        "input",
        "kv",
        "logit",
        "prefix",
        "request",
        "scheduler",
        "seq",
        "token",
    )
    return any(needle in lowered for needle in needles)


def _object_interesting_attrs(obj: Any, limit: int = 24) -> dict[str, Any]:
    result: dict[str, Any] = {}
    names: list[str] = []

    if hasattr(obj, "__dict__"):
        try:
            names.extend(str(name) for name in vars(obj).keys())
        except Exception:
            pass
    try:
        names.extend(str(name) for name in dir(obj))
    except Exception:
        pass

    seen: set[str] = set()
    for name in names:
        if name in seen or name.startswith("__") or not _interesting_attr_name(name):
            continue
        seen.add(name)
        try:
            value = getattr(obj, name)
        except Exception as exc:
            result[name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        if callable(value):
            continue
        result[name] = _summarize_value(value)
        if len(result) >= limit:
            break
    return result


def _walk_interesting_runtime_objects(root: Any, max_depth: int = 5, max_objects: int = 32) -> list[dict[str, Any]]:
    seen: set[int] = set()
    found: list[dict[str, Any]] = []

    def walk(obj: Any, path: str, depth: int) -> None:
        if obj is None or depth > max_depth or len(found) >= max_objects:
            return
        obj_id = id(obj)
        if obj_id in seen:
            return
        seen.add(obj_id)

        if _interesting_attr_name(path):
            attrs = _object_interesting_attrs(obj, limit=16)
            found.append(
                {
                    "path": path,
                    "type": _safe_type_name(obj),
                    "len": _safe_len(obj),
                    "attrs": attrs,
                }
            )

        if isinstance(obj, dict):
            for key, value in list(obj.items())[:24]:
                if isinstance(key, str) and _interesting_attr_name(key):
                    walk(value, f"{path}.{key}" if path else key, depth + 1)
            return

        if isinstance(obj, (list, tuple)):
            for index, value in enumerate(list(obj)[:12]):
                walk(value, f"{path}.{index}", depth + 1)
            return

        if hasattr(obj, "__dict__"):
            try:
                items = list(vars(obj).items())
            except Exception:
                items = []
            for name, value in items:
                if _interesting_attr_name(name):
                    walk(value, f"{path}.{name}" if path else name, depth + 1)

    walk(root, "llm", 0)
    return found


def _tokenize_prompt(llm: Any, prompt: str) -> dict[str, Any]:
    tokenizer = getattr(llm, "tokenizer", None) or getattr(llm, "llm_engine", None)
    candidates = [tokenizer]
    if tokenizer is not None:
        for attr_name in ("tokenizer", "_tokenizer", "hf_tokenizer"):
            try:
                candidates.append(getattr(tokenizer, attr_name))
            except Exception:
                pass
    for candidate in candidates:
        if candidate is None:
            continue
        encode = getattr(candidate, "encode", None)
        if callable(encode):
            try:
                token_ids = encode(prompt)
                if isinstance(token_ids, list):
                    return {
                        "available": True,
                        "token_count": len(token_ids),
                        "token_ids": [int(item) for item in token_ids],
                        "tokenizer_type": _safe_type_name(candidate),
                    }
            except Exception:
                pass
    return {"available": False}


def _output_summary(outputs: Any) -> dict[str, Any]:
    items = list(outputs or [])
    summary: dict[str, Any] = {"count": len(items), "items": []}
    for item in items[:4]:
        entry = {
            "type": _safe_type_name(item),
            "request_id": getattr(item, "request_id", None),
            "prompt_token_ids": getattr(item, "prompt_token_ids", None),
            "finished": getattr(item, "finished", None),
        }
        candidates = getattr(item, "outputs", None) or []
        entry["output_count"] = len(candidates)
        output_entries = []
        for candidate in list(candidates)[:2]:
            output_entries.append(
                {
                    "type": _safe_type_name(candidate),
                    "index": getattr(candidate, "index", None),
                    "token_ids": getattr(candidate, "token_ids", None),
                    "finish_reason": getattr(candidate, "finish_reason", None),
                    "stop_reason": getattr(candidate, "stop_reason", None),
                }
            )
        entry["outputs"] = output_entries
        summary["items"].append(entry)
    return summary


def _migration_block_table_candidate(runtime: RealVllmRuntime) -> dict[str, Any]:
    payload = runtime.last_register_payload or {}
    source_block_size = payload.get("block_size")
    layer_shapes = payload.get("layer_shapes")
    layer_shapes = layer_shapes if isinstance(layer_shapes, list) else []
    source_block_count = None
    if layer_shapes:
        first_shape = layer_shapes[0] if isinstance(layer_shapes[0], dict) else {}
        source_block_count = first_shape.get("block_count")
        key_shape = first_shape.get("key_shape")
        if source_block_count is None and isinstance(key_shape, list) and key_shape:
            source_block_count = key_shape[0]

    target_block_size = None
    try:
        cache_config = runtime.llm.llm_engine.input_processor.cache_config
        target_block_size = getattr(cache_config, "block_size", None)
    except Exception:
        target_block_size = None

    target_blocks_per_source_block = None
    target_block_count = None
    if isinstance(source_block_size, int) and isinstance(target_block_size, int) and target_block_size > 0:
        target_blocks_per_source_block = (source_block_size + target_block_size - 1) // target_block_size
        if isinstance(source_block_count, int):
            target_block_count = source_block_count * target_blocks_per_source_block
    allocation = payload.get("target_block_allocation")
    allocation = allocation if isinstance(allocation, dict) else {}
    allocated_ids = allocation.get("target_block_ids")
    allocated_ids = allocated_ids if isinstance(allocated_ids, list) else []

    return {
        "hash": payload.get("hash"),
        "layer_count": payload.get("layer_count"),
        "source_block_size": source_block_size,
        "source_block_count": source_block_count,
        "target_block_size": target_block_size,
        "target_blocks_per_source_block": target_blocks_per_source_block,
        "target_block_count": target_block_count or allocation.get("target_block_count"),
        "allocated_target_block_count": len(allocated_ids),
        "allocated_target_block_ids_sample": [int(item) for item in allocated_ids[:16]],
        "target_block_allocation_mode": allocation.get("mode"),
        "attachment_requirement": "The generated vLLM request must bind this migrated KV span through a request block table or equivalent prefix-cache entry before decode.",
    }


def _method_names_matching(obj: Any, terms: tuple[str, ...], limit: int = 48) -> list[str]:
    names: list[str] = []
    try:
        raw_names = dir(obj)
    except Exception:
        return names
    for name in raw_names:
        lower = name.lower()
        if name.startswith("__") or not any(term in lower for term in terms):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _seed_vllm_prefix_cache(runtime: RealVllmRuntime, prompt: str) -> dict[str, Any]:
    payload = runtime.last_register_payload or {}
    allocation = payload.get("target_block_allocation")
    allocation = allocation if isinstance(allocation, dict) else {}
    target_block_ids = allocation.get("target_block_ids")
    if not isinstance(target_block_ids, list) or not target_block_ids:
        return {
            "success": False,
            "reason": "No allocated vLLM target block IDs were recorded for the migrated KV payload.",
        }

    tokenization = _tokenize_prompt(runtime.llm, prompt)
    prompt_token_ids = tokenization.get("token_ids") if isinstance(tokenization, dict) else None
    if not isinstance(prompt_token_ids, list):
        return {"success": False, "reason": "Continuation prompt could not be tokenized by the target vLLM runtime."}

    try:
        from vllm import SamplingParams
        from vllm.v1.request import Request
    except Exception as exc:
        return {"success": False, "reason": f"Could not import vLLM Request/SamplingParams for prefix-cache seeding: {exc!r}"}

    try:
        engine_core = runtime.llm.llm_engine.engine_core.engine_core
        scheduler = engine_core.scheduler
        kv_cache_manager = scheduler.kv_cache_manager
        block_pool = kv_cache_manager.block_pool
        target_block_size = int(getattr(scheduler, "block_size", 0) or getattr(block_pool, "hash_block_size", 0))
        if target_block_size <= 0:
            return {"success": False, "reason": "Could not determine vLLM target block size for prefix-cache seeding."}

        request = Request(
            request_id="permeant-prefix-cache-seed",
            prompt_token_ids=[int(item) for item in prompt_token_ids],
            sampling_params=SamplingParams(max_tokens=1, temperature=0.0),
            pooling_params=None,
            block_hasher=getattr(engine_core, "request_block_hasher", None),
        )
        full_prompt_block_count = len(request.block_hashes)
        seed_block_count = min(full_prompt_block_count, len(target_block_ids))
        if seed_block_count <= 0:
            return {
                "success": False,
                "reason": "Continuation prompt has no full vLLM hash blocks; use the source prefill prompt or another prompt at least one target block long.",
                "prompt_token_count": len(prompt_token_ids),
                "target_block_size": target_block_size,
                "request_block_hash_count": full_prompt_block_count,
            }

        blocks = [block_pool.blocks[int(block_id)] for block_id in target_block_ids[:seed_block_count]]
        block_pool.cache_full_blocks(
            request=request,
            blocks=blocks,
            num_cached_blocks=0,
            num_full_blocks=seed_block_count,
            block_size=target_block_size,
            kv_cache_group_id=0,
        )
        return {
            "success": True,
            "method": "block_pool.cache_full_blocks",
            "prompt_token_count": len(prompt_token_ids),
            "target_block_size": target_block_size,
            "request_block_hash_count": full_prompt_block_count,
            "seeded_block_count": seed_block_count,
            "seeded_block_ids_sample": [int(item) for item in target_block_ids[:16]],
        }
    except Exception as exc:
        return {
            "success": False,
            "reason": f"Failed to seed vLLM prefix cache with migrated blocks: {exc!r}",
            "prompt_token_count": len(prompt_token_ids),
        }


def _migrated_decode_attachment_attempt(runtime: RealVllmRuntime, prompt: str) -> dict[str, Any]:
    terms = ("block", "cache", "prefix", "request", "hash", "alloc", "touch", "free")
    objects: dict[str, Any] = {}
    try:
        engine_core_client = runtime.llm.llm_engine.engine_core
        objects["engine_core_client"] = engine_core_client
        engine_core = getattr(engine_core_client, "engine_core", None)
        if engine_core is not None:
            objects["engine_core"] = engine_core
            scheduler = getattr(engine_core, "scheduler", None)
            if scheduler is not None:
                objects["scheduler"] = scheduler
                kv_cache_manager = getattr(scheduler, "kv_cache_manager", None)
                if kv_cache_manager is not None:
                    objects["kv_cache_manager"] = kv_cache_manager
                    block_pool = getattr(kv_cache_manager, "block_pool", None)
                    if block_pool is not None:
                        objects["block_pool"] = block_pool
    except Exception as exc:
        objects["inspection_error"] = exc

    surface: dict[str, Any] = {}
    for name, obj in objects.items():
        if isinstance(obj, BaseException):
            surface[name] = {"error": repr(obj)}
            continue
        surface[name] = {
            "type": _safe_type_name(obj),
            "interesting_attrs": _object_interesting_attrs(obj),
            "candidate_methods": _method_names_matching(obj, terms),
        }

    candidate = _migration_block_table_candidate(runtime)
    seed_result = _seed_vllm_prefix_cache(runtime, prompt)
    supported = bool(seed_result.get("success"))
    reason = (
        "Migrated blocks were seeded into vLLM prefix cache for the continuation prompt."
        if supported
        else seed_result.get("reason")
        or "No safe public vLLM request/block-table attachment API has been identified for binding migrated KV slots to LLM.generate()."
    )

    attempt = {
        "attempted": True,
        "supported": supported,
        "reason": reason,
        "migration_block_table_candidate": candidate,
        "prefix_cache_seed": seed_result,
        "runtime_attachment_surface": surface,
    }
    runtime.last_migrated_decode_attachment_attempt = attempt
    _append_probe_event({"event": "migrated_decode_attachment_attempt", "attempt": attempt})
    return attempt


def _decode_attachment_snapshot(
    runtime: RealVllmRuntime,
    prompt: str,
    stage: str,
    outputs: Any | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "stage": stage,
        "prompt": prompt,
        "prompt_tokenization": _tokenize_prompt(runtime.llm, prompt),
        "registered_hashes": sorted(runtime.registered_hashes),
        "last_registered_hash": (runtime.last_register_payload or {}).get("hash"),
        "last_registered_layer_count": (runtime.last_register_payload or {}).get("layer_count"),
        "kv_cache_key_count": len(runtime.kv_caches),
        "layer_map_count": len(runtime.permeant_layer_map),
        "runtime_metadata": runtime.metadata,
        "candidate_runtime_objects": _walk_interesting_runtime_objects(runtime.llm),
        "migrated_decode_attachment_attempt": runtime.last_migrated_decode_attachment_attempt,
    }
    if outputs is not None:
        snapshot["outputs"] = _output_summary(outputs)
    _append_probe_event({"event": "decode_attachment_snapshot", **snapshot})
    return snapshot


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
        baseline_prompt = os.getenv("PERMEANT_VLLM_CONTINUATION_PROMPT")
        if os.getenv("PERMEANT_VLLM_CONTINUATION_PROMPT_FROM_SOURCE", "0") == "1":
            baseline_prompt = (_source_continuation_reference() or {}).get("prompt") or baseline_prompt
        capture_baseline = os.getenv("PERMEANT_VLLM_CAPTURE_BASELINE", "1") != "0"
        if baseline_prompt and capture_baseline:
            _RUNTIME_SINGLETON.baseline_continuation = _RUNTIME_SINGLETON._sample_continuation(
                prompt=baseline_prompt,
                max_tokens=int(os.getenv("PERMEANT_VLLM_CONTINUATION_MAX_TOKENS", "16")),
                event_name="baseline_continuation",
            )
    return _RUNTIME_SINGLETON
