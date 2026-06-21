"""llama.cpp target-runtime adapter scaffolding for PermeantOS.

The in-tree adapter proves the practical open-source runtime boundary without
overclaiming decode fidelity. It can accept migrated canonical KV tensors,
record stable fingerprints, probe installed llama.cpp CLI/server tools, and
delegate to an optional live hook when a llama.cpp KV import surface is
available.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_adapter_utils import AdapterError, load_hook

_RUNTIME_SINGLETON: "LlamaCppReferenceRuntime | None" = None


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
    raise AdapterError("unable to determine llama.cpp request kind")


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


def _normalize_response(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"success": True}
    if isinstance(payload, bool):
        return {"success": payload}
    if not isinstance(payload, dict):
        raise AdapterError("llama.cpp runtime hook must return a JSON object, bool, or None")
    response = dict(payload)
    success = response.get("success", True)
    if not isinstance(success, bool):
        raise AdapterError("llama.cpp runtime response field 'success' must be a boolean")
    response["success"] = success
    return response


def _flatten_numeric(value: Any) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if not isinstance(value, list):
        raise AdapterError("tensor data must be numeric or nested numeric lists")
    flattened: list[float] = []
    for item in value:
        flattened.extend(_flatten_numeric(item))
    return flattened


def _f32_sha256(values: list[float]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(struct.pack("<f", float(value)))
    return "sha256:" + digest.hexdigest()


def _canonical_tensor(tensor: dict[str, Any]) -> tuple[list[int], list[float]]:
    name = tensor.get("name")
    shape = tensor.get("shape")
    if not isinstance(name, str) or not name:
        raise AdapterError("injector tensor is missing a valid name")
    if not isinstance(shape, list) or not all(isinstance(dim, int) for dim in shape):
        raise AdapterError(f"tensor {name} is missing a valid integer shape")
    if len(shape) == 4 and shape[0] == 1:
        shape = shape[1:]
    if len(shape) != 3:
        raise AdapterError(f"tensor {name} must be canonical [seq, kv_heads, head_dim], got {shape}")
    values = _flatten_numeric(tensor.get("data"))
    expected = shape[0] * shape[1] * shape[2]
    if len(values) != expected:
        raise AdapterError(f"tensor {name} contains {len(values)} values, expected {expected} for shape {shape}")
    return shape, values


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
    value = os.getenv("PERMEANT_LLAMA_CPP_RUNTIME_STATE_FILE")
    if not value:
        return None
    return Path(value).expanduser()


def _probe_file() -> Path | None:
    value = os.getenv("PERMEANT_LLAMA_CPP_RUNTIME_PROBE_FILE")
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
    _write_json(path, {**existing, "events": events})


def _proof_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _tool_path(env_name: str, default_name: str) -> str | None:
    configured = os.getenv(env_name)
    if configured:
        return configured
    return shutil.which(default_name)


def _tool_version(path: str | None) -> dict[str, Any]:
    if not path:
        return {"available": False}
    try:
        run = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10, check=False)
    except Exception as exc:
        return {"available": False, "path": path, "error": str(exc)}
    output = (run.stdout + run.stderr).strip()
    return {
        "available": run.returncode == 0,
        "path": path,
        "returncode": run.returncode,
        "version_output": output,
    }


def probe_llama_cpp_tools() -> dict[str, Any]:
    cli = _tool_path("PERMEANT_LLAMA_CPP_CLI", "llama-cli")
    server = _tool_path("PERMEANT_LLAMA_CPP_SERVER", "llama-server")
    return {
        "runtime": "llama.cpp",
        "cli": _tool_version(cli),
        "server": _tool_version(server),
        "kv_import_supported_by_default_adapter": False,
        "kv_import_requirement": "Set PERMEANT_LLAMA_CPP_RUNTIME_HOOK to a hook that can bind migrated KV state into a live llama.cpp context.",
    }


def _load_persisted_blocks() -> dict[str, dict[str, Any]]:
    path = _state_file()
    if path is None:
        return {}
    blocks = _read_json(path).get("blocks")
    return blocks if isinstance(blocks, dict) else {}


def _load_persisted_hashes() -> set[str]:
    return {hash_value for hash_value in _load_persisted_blocks() if isinstance(hash_value, str)}


def _live_hook() -> Callable[..., Any] | None:
    spec = os.getenv("PERMEANT_LLAMA_CPP_RUNTIME_HOOK")
    if not spec:
        return None
    return load_hook(spec)


class LlamaCppReferenceRuntime:
    def __init__(self) -> None:
        self.capabilities = probe_llama_cpp_tools()
        self.registered_hashes: set[str] = set()
        self.block_summaries: dict[str, dict[str, Any]] = {}
        self.last_verify_result: dict[str, Any] | None = None
        self.last_live_result: dict[str, Any] | None = None

    def register_permeant_block(self, payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
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
            key_shape, key_values = _canonical_tensor(layer["key"])
            value_shape, value_values = _canonical_tensor(layer["value"])
            if key_shape != value_shape:
                raise AdapterError(f"layer {layer_index} key/value shapes differ: {key_shape} != {value_shape}")
            layer_summaries.append(
                {
                    "layer_index": layer_index,
                    "shape": key_shape,
                    "key_sha256": _f32_sha256(key_values),
                    "value_sha256": _f32_sha256(value_values),
                    "value_count": len(key_values),
                }
            )

        accepted = {
            "hash": block_hash,
            "target_runtime": "llama.cpp",
            "adapter_mode": "accepted-state",
            "layer_count": len(layer_summaries),
            "layers": layer_summaries,
            "capabilities": self.capabilities,
            "decode_claim": "none-without-live-kv-import-hook",
        }
        live_hook = _live_hook()
        if live_hook is not None:
            live_result = _normalize_response(_invoke(live_hook, accepted, payload, request))
            self.last_live_result = live_result
            accepted["live_hook_result"] = live_result
            accepted["adapter_mode"] = "live-hook"
        self.registered_hashes.add(block_hash)
        self.block_summaries[block_hash] = accepted
        self._persist()
        _append_probe_event({"event": "register_permeant_block", **accepted})
        return {"success": True, "accepted_state": accepted}

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
            result = {
                "success": True,
                "verified_hashes": hashes,
                "decode_status": "not_attempted_without_live_kv_import_hook",
            }
            live_hook = _live_hook()
            if live_hook is not None:
                live_result = _normalize_response(_invoke(live_hook, {"verify": payload, "accepted_hashes": hashes}))
                result["live_hook_result"] = live_result
                if live_result.get("continuation") is not None:
                    result["decode_status"] = "live_hook_continuation_reported"
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
            "schema_version": "permeantos-llamacpp-reference-reverse-runtime-state-v0",
            "status": "target_runtime_state_exported",
            "target_runtime": "llama.cpp",
            "registered_hashes": sorted(set(self.registered_hashes) | _load_persisted_hashes()),
            "blocks": _load_persisted_blocks() or self.block_summaries,
            "capabilities": self.capabilities,
            "last_verify_result": self.last_verify_result,
            "last_live_result": self.last_live_result,
            "decode_claim": "none-without-live-kv-import-hook",
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

    def _persist(self) -> None:
        path = _state_file()
        if path is None:
            return
        existing = _read_json(path)
        blocks = existing.get("blocks")
        if not isinstance(blocks, dict):
            blocks = {}
        blocks.update(self.block_summaries)
        _write_json(
            path,
            {
                "target_runtime": "llama.cpp",
                "registered_hashes": sorted(blocks),
                "capabilities": self.capabilities,
                "blocks": blocks,
            },
        )


def get_runtime() -> LlamaCppReferenceRuntime:
    global _RUNTIME_SINGLETON
    if _RUNTIME_SINGLETON is None:
        _RUNTIME_SINGLETON = LlamaCppReferenceRuntime()
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
    if kind == "probe_capabilities":
        return {"success": True, "capabilities": runtime.capabilities}
    raise AdapterError(f"unsupported llama.cpp runtime request kind '{kind}'")


def injector_hook(request: dict[str, Any]) -> dict[str, Any]:
    return _normalize_response(runtime_hook(request, request))
