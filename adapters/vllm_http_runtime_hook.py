"""Target-side hook that forwards prepared payloads to a live local sidecar over HTTP."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from runtime_adapter_utils import AdapterError, normalize_injector_response


def _base_url() -> str:
    value = os.getenv("PERMEANT_VLLM_RUNTIME_URL")
    if not value:
        raise AdapterError("Set PERMEANT_VLLM_RUNTIME_URL for the HTTP runtime hook")
    return value.rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("PERMEANT_VLLM_RUNTIME_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{_base_url()}{path}",
        data=body,
        headers=_headers(),
        method="POST",
    )
    timeout_seconds = float(os.getenv("PERMEANT_VLLM_RUNTIME_TIMEOUT", "900"))
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AdapterError(f"runtime hook HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AdapterError(f"runtime hook connection failure: {exc}") from exc

    try:
        payload = json.loads(raw) if raw else {"success": True}
    except json.JSONDecodeError as exc:
        raise AdapterError(f"runtime hook returned invalid JSON: {exc}") from exc
    return normalize_injector_response(payload)


def runtime_hook(payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    if "layers" in payload:
        return _post_json("/inject_block", payload)
    if "block_hashes" in payload:
        return _post_json("/verify_continuation", payload)
    if payload.get("action") == "export_reverse_runtime_state":
        return _post_json("/export_reverse_runtime_state", payload)
    raise AdapterError("unsupported runtime hook payload")
