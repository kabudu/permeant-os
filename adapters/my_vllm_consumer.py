"""Concrete target-side consumer scaffold for a live target runtime.

This file is now usable out of the box in three modes:

- `dry_run`:
  validates that the worker can call the consumer successfully
- `http`:
  forwards the full prepared payload to a local target-runtime HTTP endpoint
- `command`:
  forwards the full prepared payload to a local command over stdin

Environment:
- `PERMEANT_VLLM_CONSUMER_MODE=dry_run|http|command`
- `PERMEANT_VLLM_INGEST_URL=http://127.0.0.1:...` for `http`
- `PERMEANT_VLLM_INGEST_TOKEN=...` optional bearer token for `http`
- `PERMEANT_VLLM_INGEST_CMD='python /path/to/runtime_ingest.py'` for `command`
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any


def _mode() -> str:
    return os.getenv("PERMEANT_VLLM_CONSUMER_MODE", "dry_run").strip().lower()


def get_target_runtime() -> dict[str, Any]:
    mode = _mode()
    if mode == "dry_run":
        return {"mode": "dry_run"}
    if mode == "http":
        url = os.getenv("PERMEANT_VLLM_INGEST_URL")
        if not url:
            raise RuntimeError("Set PERMEANT_VLLM_INGEST_URL for http consumer mode")
        return {
            "mode": "http",
            "url": url.rstrip("/"),
            "token": os.getenv("PERMEANT_VLLM_INGEST_TOKEN"),
            "timeout_seconds": float(os.getenv("PERMEANT_VLLM_INGEST_TIMEOUT", "30")),
        }
    if mode == "command":
        command = os.getenv("PERMEANT_VLLM_INGEST_CMD")
        if not command:
            raise RuntimeError("Set PERMEANT_VLLM_INGEST_CMD for command consumer mode")
        return {"mode": "command", "command": command}
    raise RuntimeError(f"Unsupported PERMEANT_VLLM_CONSUMER_MODE '{mode}'")


def _http_headers(runtime: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = runtime.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _register_via_http(runtime: dict[str, Any], payload: dict[str, Any]) -> None:
    request = urllib.request.Request(
        runtime["url"],
        data=json.dumps(payload).encode("utf-8"),
        headers=_http_headers(runtime),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=runtime["timeout_seconds"]) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP ingest failed with status {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"HTTP ingest connection failure: {exc}") from exc

    if not raw.strip():
        return
    parsed = json.loads(raw)
    if isinstance(parsed, dict) and parsed.get("success", True):
        return
    raise RuntimeError(f"HTTP ingest rejected payload: {parsed}")


def _register_via_command(runtime: dict[str, Any], payload: dict[str, Any]) -> None:
    result = subprocess.run(
        ["sh", "-c", runtime["command"]],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command ingest failed with exit code {result.returncode}")
    if not result.stdout.strip():
        return
    parsed = json.loads(result.stdout)
    if isinstance(parsed, dict) and parsed.get("success", True):
        return
    raise RuntimeError(f"command ingest rejected payload: {parsed}")


def register_prepared_block(runtime: dict[str, Any], payload: dict[str, Any]) -> None:
    if runtime["mode"] == "dry_run":
        return
    if runtime["mode"] == "http":
        _register_via_http(runtime, payload)
        return
    if runtime["mode"] == "command":
        _register_via_command(runtime, payload)
        return
    raise RuntimeError(f"Unsupported runtime mode '{runtime['mode']}'")


def consume(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = get_target_runtime()
    register_prepared_block(runtime, payload)
    return {"success": True}
