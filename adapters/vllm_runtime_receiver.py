#!/usr/bin/env python3
"""Small HTTP sidecar for a vLLM-adjacent target process.

This intentionally stops at a stable handoff boundary:
- receive prepared PermeantOS block payloads over HTTP
- persist them by block hash
- optionally call a local consumer hook for runtime-specific registration
- track acknowledgements for continuation checks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_adapter_utils import AdapterError, load_hook  # noqa: E402


def _ack_file(state_dir: Path) -> Path:
    return state_dir / "acked.json"


def _load_acknowledged(state_dir: Path) -> set[str]:
    path = _ack_file(state_dir)
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, list):
        return set()
    return {item for item in payload if isinstance(item, str)}


def _save_acknowledged(state_dir: Path, hashes: set[str]) -> None:
    _ack_file(state_dir).write_text(json.dumps(sorted(hashes), indent=2), encoding="utf-8")


def _consumer_hook():
    spec = os.getenv("PERMEANT_VLLM_CONSUMER_HOOK")
    if not spec:
        return None
    return load_hook(spec)


def _call_consumer(hook, payload: dict[str, Any]) -> dict[str, Any]:
    if hook is None:
        return {"success": True}
    result = hook(payload)
    if result is None:
        return {"success": True}
    if not isinstance(result, dict):
        raise AdapterError("consumer hook must return a dict or None")
    return result


class Receiver(BaseHTTPRequestHandler):
    server_version = "PermeantVLLMReceiver/0.1"

    @property
    def state_dir(self) -> Path:
        return self.server.state_dir  # type: ignore[attr-defined]

    @property
    def token(self) -> str | None:
        return self.server.token  # type: ignore[attr-defined]

    @property
    def hook(self):
        return self.server.consumer_hook  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:
        return

    def _reject(self, status: int, payload: dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def _require_auth(self) -> bool:
        if not self.token:
            return True
        header = self.headers.get("Authorization", "")
        if header == f"Bearer {self.token}":
            return True
        self._reject(401, {"success": False, "error": "unauthorized"})
        return False

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            raise AdapterError("request body must be a JSON object")
        return payload

    def do_POST(self) -> None:
        if not self._require_auth():
            return
        try:
            payload = self._read_json()
            if self.path == "/inject_block":
                response = self._inject(payload)
            elif self.path == "/verify_continuation":
                response = self._verify(payload)
            elif self.path == "/export_reverse_runtime_state":
                response = self._export_reverse_runtime_state(payload)
            else:
                self._reject(404, {"success": False, "error": "not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))
        except AdapterError as exc:
            self._reject(400, {"success": False, "error": str(exc)})
        except json.JSONDecodeError as exc:
            self._reject(400, {"success": False, "error": f"invalid JSON: {exc}"})
        except Exception as exc:
            self._reject(500, {"success": False, "error": str(exc)})

    def _inject(self, payload: dict[str, Any]) -> dict[str, Any]:
        block_hash = payload.get("hash")
        if not isinstance(block_hash, str) or not block_hash:
            raise AdapterError("inject_block payload requires a non-empty 'hash'")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / f"{block_hash}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        result = _call_consumer(self.hook, payload)
        if result.get("success", True):
            hashes = _load_acknowledged(self.state_dir)
            hashes.add(block_hash)
            _save_acknowledged(self.state_dir, hashes)
        return result

    def _verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        hashes = payload.get("block_hashes")
        if not isinstance(hashes, list) or not all(isinstance(item, str) for item in hashes):
            raise AdapterError("verify_continuation payload requires string list 'block_hashes'")
        acknowledged = _load_acknowledged(self.state_dir)
        missing = [item for item in hashes if item not in acknowledged]
        if missing:
            return {"success": False, "missing_hashes": missing}
        result = _call_consumer(self.hook, payload)
        if not isinstance(result, dict):
            raise AdapterError("consumer verification hook must return a dict or None")
        if result.get("success", True):
            normalized = {"success": True}
            normalized.update(result)
            return normalized
        return result

    def _export_reverse_runtime_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = {"action": "export_reverse_runtime_state"}
        request.update(payload)
        result = _call_consumer(self.hook, request)
        if not isinstance(result, dict):
            raise AdapterError("consumer reverse export hook must return a dict or None")
        if result.get("success", True):
            normalized = {"success": True}
            normalized.update(result)
            return normalized
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PermeantOS vLLM runtime receiver sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=29100)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--token", default=os.getenv("PERMEANT_VLLM_RUNTIME_TOKEN"))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Receiver)
    server.state_dir = Path(args.state_dir)  # type: ignore[attr-defined]
    server.token = args.token  # type: ignore[attr-defined]
    server.consumer_hook = _consumer_hook()  # type: ignore[attr-defined]
    print(f"PermeantOS vLLM runtime receiver listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
