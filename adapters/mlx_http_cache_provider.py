"""Source-side provider that fetches live cache material from a local HTTP exporter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from runtime_adapter_utils import AdapterError


def _base_url() -> str:
    value = os.getenv("PERMEANT_MLX_RUNTIME_URL")
    if not value:
        raise AdapterError("Set PERMEANT_MLX_RUNTIME_URL for the MLX HTTP cache provider")
    return value.rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("PERMEANT_MLX_RUNTIME_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_live_cache(request: dict[str, Any] | None = None) -> Any:
    body = json.dumps(request or {}).encode("utf-8")
    endpoint = os.getenv("PERMEANT_MLX_RUNTIME_PATH", "/extract")
    http_request = urllib.request.Request(
        f"{_base_url()}{endpoint}",
        data=body,
        headers=_headers(),
        method="POST",
    )
    timeout_seconds = float(os.getenv("PERMEANT_MLX_RUNTIME_TIMEOUT", "30"))
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AdapterError(f"MLX runtime HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AdapterError(f"MLX runtime connection failure: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"MLX runtime returned invalid JSON: {exc}") from exc
    return payload
