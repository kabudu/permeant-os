#!/usr/bin/env python3
"""Local HTTP exporter for a live MLX-hosted process."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_adapter_utils import AdapterError, load_hook, normalize_extractor_payload  # noqa: E402


def _provider_hook():
    spec = os.getenv("PERMEANT_MLX_EXPORTER_HOOK")
    if not spec:
        raise AdapterError("Set PERMEANT_MLX_EXPORTER_HOOK for the MLX runtime exporter")
    return load_hook(spec)


def _call_provider(hook, request: dict):
    result = hook(request)
    return normalize_extractor_payload(result)


def _call_import_provider(hook, request: dict) -> dict:
    result = hook(request)
    if not isinstance(result, dict):
        raise AdapterError("MLX runtime import hook must return a JSON object")
    return result


class Exporter(BaseHTTPRequestHandler):
    server_version = "PermeantMLXExporter/0.1"

    @property
    def token(self) -> str | None:
        return self.server.token  # type: ignore[attr-defined]

    @property
    def provider(self):
        return self.server.provider_hook  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:
        return

    def _reject(self, status: int, payload: dict) -> None:
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
        self._reject(401, {"error": "unauthorized"})
        return False

    def do_GET(self) -> None:
        if self.path not in ("/", "/health"):
            self._reject(404, {"error": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "service": "mlx_runtime_exporter"}).encode("utf-8"))

    def do_POST(self) -> None:
        if not self._require_auth():
            return
        if self.path not in ("/extract", "/import-reverse-state"):
            self._reject(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            request = json.loads(raw) if raw else {}
            if not isinstance(request, dict):
                raise AdapterError("request body must be a JSON object")
            if self.path == "/extract":
                payload = _call_provider(self.provider, request)
            else:
                request.setdefault("action", "import_reverse_runtime_state")
                payload = _call_import_provider(self.provider, request)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        except AdapterError as exc:
            self._reject(400, {"error": str(exc)})
        except json.JSONDecodeError as exc:
            self._reject(400, {"error": f"invalid JSON: {exc}"})
        except Exception as exc:
            self._reject(500, {"error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PermeantOS MLX runtime exporter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=29101)
    parser.add_argument("--token", default=os.getenv("PERMEANT_MLX_RUNTIME_TOKEN"))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Exporter)
    server.token = args.token  # type: ignore[attr-defined]
    server.provider_hook = _provider_hook()  # type: ignore[attr-defined]
    print(f"PermeantOS MLX runtime exporter listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
