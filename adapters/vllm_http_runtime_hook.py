"""Target-side hook that forwards prepared payloads to a live local sidecar over HTTP."""

from __future__ import annotations

import json
import os
import sys
from time import perf_counter
import urllib.error
import urllib.request
from typing import Any

from runtime_adapter_utils import AdapterError, normalize_injector_response
from vllm_binary_blocks import CONTENT_TYPE


def _base_url() -> str:
    value = os.getenv("PERMEANT_VLLM_RUNTIME_URL")
    if not value:
        raise AdapterError("Set PERMEANT_VLLM_RUNTIME_URL for the HTTP runtime hook")
    return value.rstrip("/")


def _headers(content_type: str) -> dict[str, str]:
    headers = {"Content-Type": content_type}
    token = os.getenv("PERMEANT_VLLM_RUNTIME_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    started = perf_counter()
    body = json.dumps(payload).encode("utf-8")
    return _post_body(path, body, "application/json", encode_ms=(perf_counter() - started) * 1000)


def post_binary_block(body: bytes) -> dict[str, Any]:
    return _post_body("/inject_binary_block", body, CONTENT_TYPE, strict=True)


def _post_body(
    path: str, body: bytes, content_type: str, *, encode_ms: float = 0, strict: bool = False
) -> dict[str, Any]:
    started = perf_counter()
    request = urllib.request.Request(
        f"{_base_url()}{path}",
        data=body,
        headers=_headers(content_type),
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
    if os.getenv("PERMEANT_INJECTOR_PROFILE") == "1":
        print(
            f"[Injector HTTP] request_bytes={len(body)} encode_ms={encode_ms:.3f}"
            f" round_trip_ms={(perf_counter() - started) * 1000:.3f}",
            file=sys.stderr,
        )

    try:
        payload = json.loads(raw) if raw else {"success": True}
    except json.JSONDecodeError as exc:
        raise AdapterError(f"runtime hook returned invalid JSON: {exc}") from exc
    if strict and (not raw or not isinstance(payload, dict) or type(payload.get("success")) is not bool):
        raise AdapterError("binary injector response must explicitly acknowledge success or failure")
    return normalize_injector_response(payload)


def runtime_hook(payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    if "layers" in payload:
        return _post_json("/inject_block", payload)
    if "block_hashes" in payload:
        return _post_json("/verify_continuation", payload)
    if payload.get("action") == "export_reverse_runtime_state":
        return _post_json("/export_reverse_runtime_state", payload)
    raise AdapterError("unsupported runtime hook payload")
