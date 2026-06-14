#!/usr/bin/env python3
import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Callable


class AdapterError(RuntimeError):
    pass


def load_json_stdin() -> Any:
    raw = __import__("sys").stdin.read().strip()
    if not raw:
        raise AdapterError("empty JSON request on stdin")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"invalid JSON request: {exc}") from exc


def load_json_file(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError as exc:
        raise AdapterError(f"fixture file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AdapterError(f"invalid JSON fixture at {path}: {exc}") from exc


def dump_json_stdout(payload: Any) -> None:
    __import__("sys").stdout.write(json.dumps(payload))
    __import__("sys").stdout.flush()


def _infer_shape(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    if not value:
        return [0]
    child_shapes = [_infer_shape(item) for item in value]
    first = child_shapes[0]
    for shape in child_shapes[1:]:
        if shape != first:
            raise AdapterError("tensor data has a ragged nested shape")
    return [len(value)] + first


def _flatten_numeric(value: Any) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if not isinstance(value, list):
        raise AdapterError("tensor data must be numeric or nested numeric lists")
    flattened: list[float] = []
    for item in value:
        flattened.extend(_flatten_numeric(item))
    return flattened


def load_hook(spec: str) -> Callable[[Any], Any]:
    if ":" not in spec:
        raise AdapterError("hook spec must look like module:function or /path/to/file.py:function")

    module_spec, function_name = spec.rsplit(":", 1)
    if module_spec.endswith(".py") or "/" in module_spec:
        module_path = Path(module_spec).expanduser().resolve()
        if not module_path.exists():
            raise AdapterError(f"hook module path does not exist: {module_path}")
        module_name = f"permeant_hook_{module_path.stem}_{abs(hash(str(module_path)))}"
        spec_obj = importlib.util.spec_from_file_location(module_name, module_path)
        if spec_obj is None or spec_obj.loader is None:
            raise AdapterError(f"failed to load hook module from path: {module_path}")
        module = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(module)
    else:
        module = importlib.import_module(module_spec)

    hook = getattr(module, function_name, None)
    if hook is None or not callable(hook):
        raise AdapterError(f"hook function not found or not callable: {function_name}")
    return hook


def normalize_extractor_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        payload = {"tensors": payload}
    if not isinstance(payload, dict):
        raise AdapterError("extractor payload must be an object or tensor list")

    tensors = payload.get("tensors")
    if not isinstance(tensors, list):
        raise AdapterError("extractor payload must contain a 'tensors' list")

    normalized = []
    for idx, tensor in enumerate(tensors):
        if not isinstance(tensor, dict):
            raise AdapterError(f"tensor {idx} must be an object")
        name = tensor.get("name")
        shape = tensor.get("shape")
        data = tensor.get("data")
        if not isinstance(name, str) or not name:
            raise AdapterError(f"tensor {idx} is missing a valid 'name'")
        if shape is None:
            shape = _infer_shape(data)
        if not isinstance(shape, list) or not all(isinstance(x, int) for x in shape):
            raise AdapterError(f"tensor {idx} has an invalid 'shape'")
        try:
            flat_data = _flatten_numeric(data)
        except AdapterError as exc:
            raise AdapterError(f"tensor {idx} has invalid 'data': {exc}") from exc
        if not isinstance(data, list):
            raise AdapterError(f"tensor {idx} has invalid 'data'")
        normalized.append({
            "name": name,
            "shape": shape,
            "data": flat_data,
        })

    return {"tensors": normalized}


def normalize_injector_response(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"success": True}
    if not isinstance(payload, dict):
        raise AdapterError("injector response must be a JSON object")

    success = payload.get("success", True)
    if not isinstance(success, bool):
        raise AdapterError("injector response field 'success' must be a boolean when present")

    response = {"success": success}
    if "error" in payload:
        if payload["error"] is not None and not isinstance(payload["error"], str):
            raise AdapterError("injector response field 'error' must be a string when present")
        response["error"] = payload["error"]
    if "missing_hashes" in payload:
        missing = payload["missing_hashes"]
        if not isinstance(missing, list) or not all(isinstance(x, str) for x in missing):
            raise AdapterError("injector response field 'missing_hashes' must be a string list when present")
        response["missing_hashes"] = missing
    return response
