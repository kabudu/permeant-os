#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MAX_FRAME_BYTES = int(os.getenv("PERMEANT_BRIDGE_MAX_FRAME_BYTES", str(500 * 1024 * 1024)))
DEFAULT_SOCKET_TIMEOUT = float(os.getenv("PERMEANT_BRIDGE_SOCKET_TIMEOUT", "30"))
DEFAULT_HTTP_TIMEOUT = float(os.getenv("PERMEANT_BRIDGE_HTTP_TIMEOUT", "60"))


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def read_exact(stream: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.recv(remaining)
        if not chunk:
            raise EOFError(f"expected {remaining} more bytes")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: socket.socket) -> bytes:
    header = read_exact(stream, 4)
    frame_size = int.from_bytes(header, "big")
    if frame_size > MAX_FRAME_BYTES:
        raise ValueError(f"frame size too large: {frame_size}")
    payload = read_exact(stream, frame_size)
    return header + payload


def read_http_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", "0"))
    return handler.rfile.read(length)


class SessionRegistry:
    def __init__(self, target_host: str, target_port: int, timeout_seconds: float) -> None:
        self.target_host = target_host
        self.target_port = target_port
        self.timeout_seconds = timeout_seconds
        self._sessions: dict[str, socket.socket] = {}
        self._lock = threading.Lock()

    def open(self) -> str:
        stream = socket.create_connection((self.target_host, self.target_port), timeout=self.timeout_seconds)
        stream.settimeout(self.timeout_seconds)
        session_id = uuid.uuid4().hex
        with self._lock:
            self._sessions[session_id] = stream
        return session_id

    def exchange(self, session_id: str, frame: bytes) -> bytes:
        with self._lock:
            stream = self._sessions.get(session_id)
        if stream is None:
            raise KeyError(f"unknown session '{session_id}'")
        stream.sendall(frame)
        return read_frame(stream)

    def close(self, session_id: str) -> None:
        with self._lock:
            stream = self._sessions.pop(session_id, None)
        if stream is not None:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            stream.close()


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "PermeantBridge/0.1"

    @property
    def registry(self) -> SessionRegistry:
        return self.server.registry  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            if self.path == "/open":
                session_id = self.registry.open()
                body = json.dumps({"session_id": session_id}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/exchange":
                session_id = self.headers.get("X-Session-Id")
                if not session_id:
                    self.send_error(HTTPStatus.BAD_REQUEST, "missing X-Session-Id")
                    return
                frame = read_http_body(self)
                response_frame = self.registry.exchange(session_id, frame)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(response_frame)))
                self.end_headers()
                self.wfile.write(response_frame)
                return

            if self.path == "/close":
                session_id = self.headers.get("X-Session-Id")
                if not session_id:
                    self.send_error(HTTPStatus.BAD_REQUEST, "missing X-Session-Id")
                    return
                self.registry.close(session_id)
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return

            self.send_error(HTTPStatus.NOT_FOUND)
        except EOFError as exc:
            self.send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        except KeyError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:  # pragma: no cover - best effort bridge
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def post_bytes(url: str, body: bytes, headers: dict[str, str], timeout_seconds: float) -> bytes:
    merged_headers = {
        "User-Agent": "curl/8.7.1",
        "Accept": "*/*",
        **headers,
    }
    request = urllib.request.Request(url, data=body, headers=merged_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request to {url} failed: {exc}") from exc


def open_remote_session(base_url: str, timeout_seconds: float) -> str:
    raw = post_bytes(f"{base_url}/open", b"{}", {"Content-Type": "application/json"}, timeout_seconds)
    payload = json.loads(raw.decode("utf-8"))
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("remote bridge returned invalid session id")
    return session_id


def close_remote_session(base_url: str, session_id: str, timeout_seconds: float) -> None:
    post_bytes(f"{base_url}/close", b"", {"X-Session-Id": session_id}, timeout_seconds)


def exchange_remote_frame(base_url: str, session_id: str, frame: bytes, timeout_seconds: float) -> bytes:
    return post_bytes(
        f"{base_url}/exchange",
        frame,
        {
            "Content-Type": "application/octet-stream",
            "X-Session-Id": session_id,
        },
        timeout_seconds,
    )


def handle_local_client(client: socket.socket, remote_url: str, timeout_seconds: float) -> None:
    client.settimeout(DEFAULT_SOCKET_TIMEOUT)
    session_id = open_remote_session(remote_url, timeout_seconds)
    try:
        while True:
            try:
                frame = read_frame(client)
            except EOFError:
                break
            response_frame = exchange_remote_frame(remote_url, session_id, frame, timeout_seconds)
            client.sendall(response_frame)
    finally:
        try:
            close_remote_session(remote_url, session_id, timeout_seconds)
        except Exception:
            pass
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        client.close()


def run_server(args: argparse.Namespace) -> int:
    registry = SessionRegistry(args.target_host, args.target_port, args.socket_timeout)
    httpd = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    httpd.registry = registry  # type: ignore[attr-defined]
    print(
        f"Permeant Runpod HTTP bridge server listening on http://{args.host}:{args.port} -> {args.target_host}:{args.target_port}",
        flush=True,
    )
    httpd.serve_forever()
    return 0


def run_client(args: argparse.Namespace) -> int:
    remote_url = args.remote_url.rstrip("/")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(1)
    print(
        f"Permeant Runpod HTTP bridge client listening on {args.host}:{args.port} -> {remote_url}",
        flush=True,
    )
    try:
        while True:
            client, addr = listener.accept()
            print(f"Accepted local client from {addr[0]}:{addr[1]}", flush=True)
            try:
                handle_local_client(client, remote_url, args.http_timeout)
            except Exception as exc:
                print(f"bridge client error: {exc}", file=sys.stderr, flush=True)
            if args.once:
                break
    finally:
        listener.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge PermeantOS daemon traffic over Runpod HTTP proxy")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    server = subparsers.add_parser("server", help="Run on the pod and bridge HTTP requests to the local daemon TCP port")
    server.add_argument("--host", default="0.0.0.0")
    server.add_argument("--port", type=int, default=19123)
    server.add_argument("--target-host", default="127.0.0.1")
    server.add_argument("--target-port", type=int, default=29099)
    server.add_argument("--socket-timeout", type=float, default=DEFAULT_SOCKET_TIMEOUT)

    client = subparsers.add_parser("client", help="Run locally and present a TCP target backed by the remote HTTP bridge")
    client.add_argument("--host", default="127.0.0.1")
    client.add_argument("--port", type=int, default=39099)
    client.add_argument("--remote-url", required=True)
    client.add_argument("--http-timeout", type=float, default=DEFAULT_HTTP_TIMEOUT)
    client.add_argument("--once", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "server":
        return run_server(args)
    if args.mode == "client":
        return run_client(args)
    return fail(f"unknown mode '{args.mode}'")


if __name__ == "__main__":
    raise SystemExit(main())
