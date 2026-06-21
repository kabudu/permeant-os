"""Reference PyTorch target-runtime adapter for PermeantOS.

The adapter is intentionally boring: it accepts canonical PermeantOS KV tensors,
materializes them as PyTorch tensors when `torch` is available, and otherwise
uses a list-backed runtime with the same validation and evidence surface. The
fallback keeps CI and offline evidence runs independent of a heavyweight
PyTorch install while preserving the adapter contract.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_adapter_utils import AdapterError, load_hook

try:  # pragma: no cover - exercised only when torch is installed locally.
    import torch as _torch
except Exception:  # pragma: no cover - the fallback is the common CI path.
    _torch = None

_RUNTIME_SINGLETON: "ReferencePytorchRuntime | None" = None


def _request_kind(request: dict[str, Any]) -> str:
    if "kind" in request and isinstance(request["kind"], str):
        return request["kind"]
    if "action" in request and isinstance(request["action"], str):
        return request["action"]
    if "inject_block" in request:
        return "inject_block"
    if "verify_continuation" in request:
        return "verify_continuation"
    if "tensors" in request and ("hash" in request or "block_hash" in request):
        return "inject_block"
    if "block_hashes" in request or "expected_hashes" in request:
        return "verify_continuation"
    raise AdapterError("unable to determine PyTorch injector request kind")


def _payload_for_kind(request: dict[str, Any], kind: str) -> dict[str, Any]:
    nested = request.get(kind)
    if isinstance(nested, dict):
        return nested
    return request


def _supported_args(callable_obj: Callable[..., Any]) -> int | None:
    signature = inspect.signature(callable_obj)
    positional = [
        param
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values()):
        return None
    return len(positional)


def _invoke(callable_obj: Callable[..., Any], *candidate_args: Any) -> Any:
    arg_count = _supported_args(callable_obj)
    if arg_count is None:
        return callable_obj(*candidate_args)
    return callable_obj(*candidate_args[:arg_count])


def _f32_sha256(values: list[float]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(struct.pack("<f", float(value)))
    return "sha256:" + digest.hexdigest()


def _shape_of(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            return [int(item) for item in shape]
        except Exception:
            pass

    dims: list[int] = []
    cursor = value
    while isinstance(cursor, list):
        dims.append(len(cursor))
        cursor = cursor[0] if cursor else []
    return dims


def _flatten_numeric(value: Any) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if not isinstance(value, list):
        raise AdapterError("tensor data must be numeric or nested numeric lists")
    flattened: list[float] = []
    for item in value:
        flattened.extend(_flatten_numeric(item))
    return flattened


def _nested_from_flat(values: list[float], shape: list[int]) -> Any:
    if not shape:
        if len(values) != 1:
            raise AdapterError("scalar tensor shape cannot contain multiple values")
        return values[0]
    if shape[0] < 0:
        raise AdapterError("tensor shape cannot contain negative dimensions")
    stride = 1
    for dim in shape[1:]:
        if dim < 0:
            raise AdapterError("tensor shape cannot contain negative dimensions")
        stride *= dim
    expected = shape[0] * stride
    if len(values) != expected:
        raise AdapterError(f"flat tensor data length {len(values)} does not match shape {shape}")
    return [_nested_from_flat(values[index : index + stride], shape[1:]) for index in range(0, len(values), stride)]


def _canonical_tensor_data(tensor: dict[str, Any]) -> tuple[list[int], list[float], Any]:
    name = tensor.get("name")
    shape = tensor.get("shape")
    data = tensor.get("data")
    if not isinstance(name, str) or not name:
        raise AdapterError("injector tensor is missing a valid name")
    if not isinstance(shape, list) or not all(isinstance(dim, int) for dim in shape):
        raise AdapterError(f"tensor {name} is missing a valid integer shape")
    if len(shape) == 4 and shape[0] == 1:
        shape = shape[1:]
    if len(shape) != 3:
        raise AdapterError(f"tensor {name} must be canonical [seq, kv_heads, head_dim], got {shape}")
    values = _flatten_numeric(data)
    expected = shape[0] * shape[1] * shape[2]
    if len(values) != expected:
        raise AdapterError(f"tensor {name} contains {len(values)} values, expected {expected} for shape {shape}")
    nested = _nested_from_flat(values, shape)
    return shape, values, nested


def _group_layer_tensors(tensors: list[dict[str, Any]]) -> dict[int, dict[str, dict[str, Any]]]:
    grouped: dict[int, dict[str, dict[str, Any]]] = {}
    for tensor in tensors:
        name = tensor.get("name")
        if not isinstance(name, str):
            raise AdapterError("injector tensor name must be a string")
        parts = name.split(".")
        if len(parts) != 3 or parts[0] != "layer" or parts[2] not in {"key", "value"}:
            raise AdapterError(f"unexpected tensor name '{name}'")
        try:
            layer_index = int(parts[1])
        except ValueError as exc:
            raise AdapterError(f"invalid layer index in tensor name '{name}'") from exc
        grouped.setdefault(layer_index, {})[parts[2]] = tensor
    return grouped


def _state_file() -> Path | None:
    value = os.getenv("PERMEANT_PYTORCH_RUNTIME_STATE_FILE")
    if not value:
        return None
    return Path(value).expanduser()


def _probe_file() -> Path | None:
    value = os.getenv("PERMEANT_PYTORCH_RUNTIME_PROBE_FILE")
    if not value:
        return None
    return Path(value).expanduser()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_probe_event(payload: dict[str, Any]) -> None:
    path = _probe_file()
    if path is None:
        return
    existing = _read_json(path)
    events = existing.get("events")
    if not isinstance(events, list):
        events = []
    events.append({"epoch_s": time.time(), **payload})
    existing["events"] = events
    _write_json(path, existing)


def _proof_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _normalize_response(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"success": True}
    if isinstance(payload, bool):
        return {"success": payload}
    if not isinstance(payload, dict):
        raise AdapterError("PyTorch runtime hook must return a JSON object, bool, or None")
    response = dict(payload)
    success = response.get("success", True)
    if not isinstance(success, bool):
        raise AdapterError("PyTorch runtime response field 'success' must be a boolean")
    response["success"] = success
    return response


class ReferencePytorchRuntime:
    """Small target runtime that records migrated KV state in PyTorch form."""

    def __init__(self, device: str | None = None, dtype: str | None = None) -> None:
        self.device = device or os.getenv("PERMEANT_PYTORCH_DEVICE", "cpu")
        self.dtype_name = dtype or os.getenv("PERMEANT_PYTORCH_DTYPE", "float32")
        self.tensor_backend = "torch" if _torch is not None else "python-list"
        self.kv_cache: dict[int, dict[str, Any]] = {}
        self.registered_hashes: set[str] = set()
        self.block_summaries: dict[str, dict[str, Any]] = {}
        self.last_verify_result: dict[str, Any] | None = None
        self.last_continuation_proof: dict[str, Any] | None = None

    def _materialize_tensor(self, nested: Any) -> Any:
        if _torch is None:
            return nested
        dtype = getattr(_torch, self.dtype_name, _torch.float32)
        return _torch.tensor(nested, dtype=dtype, device=self.device)

    def register_permeant_block(self, payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
        del request
        block_hash = payload.get("hash") or payload.get("block_hash")
        if not isinstance(block_hash, str) or not block_hash:
            raise AdapterError("inject_block request must include a non-empty hash")
        tensors = payload.get("tensors")
        if not isinstance(tensors, list) or not tensors:
            raise AdapterError("inject_block request must include a non-empty tensors list")

        grouped = _group_layer_tensors(tensors)
        layer_summaries: list[dict[str, Any]] = []
        for layer_index in sorted(grouped):
            layer = grouped[layer_index]
            if "key" not in layer or "value" not in layer:
                raise AdapterError(f"layer {layer_index} is missing key/value tensors")

            key_shape, key_values, key_nested = _canonical_tensor_data(layer["key"])
            value_shape, value_values, value_nested = _canonical_tensor_data(layer["value"])
            if key_shape != value_shape:
                raise AdapterError(f"layer {layer_index} key/value shapes differ: {key_shape} != {value_shape}")

            self.kv_cache[layer_index] = {
                "key": self._materialize_tensor(key_nested),
                "value": self._materialize_tensor(value_nested),
            }
            layer_summaries.append(
                {
                    "layer_index": layer_index,
                    "shape": key_shape,
                    "key_sha256": _f32_sha256(key_values),
                    "value_sha256": _f32_sha256(value_values),
                    "value_count": len(key_values),
                }
            )

        self.registered_hashes.add(block_hash)
        summary = {
            "hash": block_hash,
            "target_runtime": "pytorch-reference",
            "tensor_backend": self.tensor_backend,
            "device": self.device,
            "dtype": self.dtype_name,
            "layer_count": len(layer_summaries),
            "layers": layer_summaries,
        }
        self.block_summaries[block_hash] = summary
        _persist_runtime_summary(self)
        _append_probe_event({"event": "register_permeant_block", **summary})
        return {"success": True, "accepted_state": summary}

    def verify_permeant_hashes(self, payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
        del request
        hashes = payload.get("block_hashes") or payload.get("expected_hashes")
        if not isinstance(hashes, list) or not all(isinstance(item, str) for item in hashes):
            raise AdapterError("verify_continuation requires a string list of block hashes")
        available = set(self.registered_hashes) | _load_persisted_hashes()
        missing = [hash_value for hash_value in hashes if hash_value not in available]
        if missing:
            result = {"success": False, "missing_hashes": missing}
        else:
            result = {"success": True, "verified_hashes": hashes}
            prompt = payload.get("prompt") or payload.get("continuation_prompt")
            if isinstance(prompt, str) and prompt:
                result["continuation_proof"] = self._build_continuation_proof(prompt, hashes)
        self.last_verify_result = result
        _append_probe_event({"event": "verify_permeant_hashes", **result})
        return result

    def export_reverse_runtime_state(
        self,
        payload: dict[str, Any] | None = None,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del payload, request
        state = {
            "schema_version": "permeantos-pytorch-reference-reverse-runtime-state-v0",
            "status": "target_runtime_state_exported",
            "target_runtime": "pytorch-reference",
            "tensor_backend": self.tensor_backend,
            "device": self.device,
            "dtype": self.dtype_name,
            "registered_hashes": sorted(set(self.registered_hashes) | _load_persisted_hashes()),
            "blocks": _load_persisted_blocks() or self.block_summaries,
            "last_verify_result": self.last_verify_result,
            "last_continuation_proof": self.last_continuation_proof,
        }
        state["proof_hash"] = _proof_hash(state)
        _append_probe_event(
            {
                "event": "reverse_runtime_state_export_api",
                "proof_hash": state["proof_hash"],
                "registered_hash_count": len(state["registered_hashes"]),
            }
        )
        return {"success": True, "reverse_runtime_state": state, **state}

    def _build_continuation_proof(self, prompt: str, hashes: list[str]) -> dict[str, Any]:
        payload = {
            "target_runtime": "pytorch-reference",
            "prompt": prompt,
            "verified_hashes": hashes,
            "registered_hashes": sorted(set(self.registered_hashes) | _load_persisted_hashes()),
            "layer_count": len(self.kv_cache),
        }
        proof = {
            **payload,
            "proof_hash": _proof_hash(payload),
            "note": "Reference PyTorch target accepted migrated KV tensors; no language decode is claimed.",
        }
        self.last_continuation_proof = proof
        return proof


def _load_persisted_blocks() -> dict[str, dict[str, Any]]:
    path = _state_file()
    if path is None:
        return {}
    payload = _read_json(path)
    blocks = payload.get("blocks")
    return blocks if isinstance(blocks, dict) else {}


def _load_persisted_hashes() -> set[str]:
    blocks = _load_persisted_blocks()
    return {hash_value for hash_value in blocks if isinstance(hash_value, str)}


def _persist_runtime_summary(runtime: ReferencePytorchRuntime) -> None:
    path = _state_file()
    if path is None:
        return
    existing = _read_json(path)
    blocks = existing.get("blocks")
    if not isinstance(blocks, dict):
        blocks = {}
    blocks.update(runtime.block_summaries)
    payload = {
        "target_runtime": "pytorch-reference",
        "tensor_backend": runtime.tensor_backend,
        "device": runtime.device,
        "dtype": runtime.dtype_name,
        "registered_hashes": sorted(blocks),
        "blocks": blocks,
    }
    _write_json(path, payload)


def get_runtime() -> ReferencePytorchRuntime:
    global _RUNTIME_SINGLETON
    if _RUNTIME_SINGLETON is None:
        _RUNTIME_SINGLETON = ReferencePytorchRuntime()
    return _RUNTIME_SINGLETON


def runtime_hook(payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = get_runtime()
    kind = _request_kind(payload)
    if kind == "inject_block":
        return runtime.register_permeant_block(_payload_for_kind(payload, "inject_block"), request)
    if kind == "verify_continuation":
        return runtime.verify_permeant_hashes(_payload_for_kind(payload, "verify_continuation"), request)
    if kind == "export_reverse_runtime_state":
        return runtime.export_reverse_runtime_state(payload, request)
    raise AdapterError(f"unsupported PyTorch runtime request kind '{kind}'")


def runtime_hook_from_env() -> Callable[..., Any] | None:
    spec = os.getenv("PERMEANT_PYTORCH_RUNTIME_HOOK")
    if not spec:
        return None
    return load_hook(spec)


def injector_hook(request: dict[str, Any]) -> dict[str, Any]:
    runtime_hook_override = runtime_hook_from_env()
    hook = runtime_hook_override or runtime_hook
    return _normalize_response(_invoke(hook, request, request))
