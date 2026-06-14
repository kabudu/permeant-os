"""Live target-runtime registration hook for vLLM-adjacent runtimes.

Environment:
- PERMEANT_VLLM_RUNTIME_TARGET: required `module:symbol` or `/path/to/file.py:symbol`
- PERMEANT_VLLM_RUNTIME_REGISTER_METHOD: optional, defaults to `register_permeant_block`
- PERMEANT_VLLM_RUNTIME_VERIFY_METHOD: optional, defaults to `verify_permeant_hashes`
- PERMEANT_VLLM_RUNTIME_STATE_FILE: optional JSON state file storing registered hashes

The target spec should resolve either to:
- a runtime object, or
- a provider callable returning the runtime object

The runtime object may implement:
- `register_permeant_block(payload, request=None)`
- `verify_permeant_hashes(payload, request=None)`

If no verify method is present, this hook falls back to the registered hash state it maintains.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

_REGISTERED_HASHES: set[str] = set()


def _state_file() -> Path | None:
    value = os.getenv("PERMEANT_VLLM_RUNTIME_STATE_FILE")
    if not value:
        return None
    return Path(value).expanduser()


def _load_state_hashes() -> set[str]:
    path = _state_file()
    if path is None or not path.exists():
        return set()
    payload = json.loads(path.read_text())
    hashes = payload.get("registered_hashes", [])
    if not isinstance(hashes, list):
        return set()
    return {item for item in hashes if isinstance(item, str)}


def _store_hash(hash_value: str) -> None:
    _REGISTERED_HASHES.add(hash_value)
    path = _state_file()
    if path is None:
        return
    existing = _load_state_hashes()
    existing.add(hash_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"registered_hashes": sorted(existing)}, indent=2))


def _normalize_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {"success": True}
    if isinstance(result, bool):
        return {"success": result}
    if isinstance(result, dict):
        success = result.get("success")
        if success is None:
            normalized = dict(result)
            normalized["success"] = True
            return normalized
        return dict(result)
    raise TypeError(f"runtime hook returned unsupported result type: {type(result).__name__}")


def _supported_args(callable_obj: Any) -> int | None:
    signature = inspect.signature(callable_obj)
    positional = [
        param
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values()):
        return None
    return len(positional)


def _invoke(callable_obj: Any, *candidate_args: Any) -> Any:
    arg_count = _supported_args(callable_obj)
    if arg_count is None:
        return callable_obj(*candidate_args)
    return callable_obj(*candidate_args[:arg_count])


def _load_symbol(spec: str) -> Any:
    module_part, symbol_name = spec.rsplit(":", 1)
    module_part = module_part.strip()
    symbol_name = symbol_name.strip()
    path = Path(module_part).expanduser()

    if module_part.endswith(".py") or path.exists():
        resolved = path.resolve()
        module_name = f"permeant_vllm_runtime_{resolved.stem}_{abs(hash(str(resolved)))}"
        module_spec = importlib.util.spec_from_file_location(module_name, resolved)
        if module_spec is None or module_spec.loader is None:
            raise RuntimeError(f"unable to load runtime module from {resolved}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_part)

    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        raise RuntimeError(f"runtime target symbol '{symbol_name}' not found in '{module_part}'") from exc


def _resolve_runtime(payload: dict[str, Any], request: dict[str, Any] | None) -> Any:
    spec = os.getenv("PERMEANT_VLLM_RUNTIME_TARGET")
    if not spec:
        raise RuntimeError("set PERMEANT_VLLM_RUNTIME_TARGET for live target-runtime registration")
    symbol = _load_symbol(spec)
    if callable(symbol):
        return _invoke(symbol, payload, request)
    return symbol


def _register_method_name() -> str:
    return os.getenv("PERMEANT_VLLM_RUNTIME_REGISTER_METHOD", "register_permeant_block")


def _verify_method_name() -> str:
    return os.getenv("PERMEANT_VLLM_RUNTIME_VERIFY_METHOD", "verify_permeant_hashes")


def _verify_from_state(block_hashes: list[str]) -> dict[str, Any]:
    available = set(_REGISTERED_HASHES) | _load_state_hashes()
    missing = [hash_value for hash_value in block_hashes if hash_value not in available]
    if missing:
        return {"success": False, "missing_hashes": missing}
    return {"success": True}


def runtime_hook(payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = _resolve_runtime(payload, request)

    if "layers" in payload:
        method = getattr(runtime, _register_method_name(), None)
        if method is None:
            raise RuntimeError(f"runtime object is missing register method '{_register_method_name()}'")
        result = _normalize_result(_invoke(method, payload, request))
        if result.get("success"):
            hash_value = payload.get("hash")
            if isinstance(hash_value, str) and hash_value:
                _store_hash(hash_value)
        return result

    if "block_hashes" in payload:
        method = getattr(runtime, _verify_method_name(), None)
        if method is not None:
            return _normalize_result(_invoke(method, payload, request))
        return _verify_from_state(payload.get("block_hashes", []))

    raise RuntimeError("unsupported payload for live target-runtime registration")
