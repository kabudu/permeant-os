#!/usr/bin/env python3
"""Minimal WSS/mTLS byte proxy for PermeantOS migration streams.

The proxy intentionally carries opaque bytes. It lets the existing daemon
protocol run through the production transport path while the Rust daemon and CLI
are cut over incrementally.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
from typing import BinaryIO


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BUFFER_SIZE = 64 * 1024


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise EOFError("socket closed while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_http_headers(sock: socket.socket) -> str:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError("socket closed before HTTP headers completed")
        data.extend(chunk)
        if len(data) > 64 * 1024:
            raise ValueError("WebSocket handshake headers too large")
    return data.decode("utf-8", errors="replace")


def _parse_header_value(headers: str, name: str) -> str | None:
    prefix = name.lower() + ":"
    for line in headers.split("\r\n"):
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _server_handshake(sock: socket.socket) -> None:
    headers = _read_http_headers(sock)
    key = _parse_header_value(headers, "Sec-WebSocket-Key")
    if not key:
        raise ValueError("missing Sec-WebSocket-Key")
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    sock.sendall(response.encode("ascii"))


def _client_handshake(sock: socket.socket, host: str) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET /permeant-transport HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = _read_http_headers(sock)
    if " 101 " not in response.split("\r\n", 1)[0]:
        raise ValueError(f"WebSocket upgrade failed: {response.splitlines()[0] if response else 'empty response'}")


def _send_ws_frame(sock: socket.socket, payload: bytes, *, mask: bool) -> None:
    header = bytearray([0x82])
    length = len(payload)
    mask_bit = 0x80 if mask else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length <= 0xFFFF:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))
    if mask:
        masking_key = os.urandom(4)
        header.extend(masking_key)
        payload = bytes(byte ^ masking_key[index % 4] for index, byte in enumerate(payload))
    sock.sendall(header + payload)


def _recv_ws_frame(sock: socket.socket, *, expect_masked: bool) -> bytes:
    first, second = _recv_exact(sock, 2)
    opcode = first & 0x0F
    if opcode == 0x8:
        raise EOFError("WebSocket close frame received")
    if opcode != 0x2:
        raise ValueError(f"unsupported WebSocket opcode: {opcode}")
    masked = bool(second & 0x80)
    if masked != expect_masked:
        raise ValueError("unexpected WebSocket mask state")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    masking_key = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length)
    if masked:
        payload = bytes(byte ^ masking_key[index % 4] for index, byte in enumerate(payload))
    return payload


def _pipe_tcp_to_ws(source: socket.socket, websocket: socket.socket, *, mask: bool) -> None:
    try:
        while True:
            chunk = source.recv(BUFFER_SIZE)
            if not chunk:
                return
            _send_ws_frame(websocket, chunk, mask=mask)
    finally:
        try:
            websocket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _pipe_ws_to_tcp(websocket: socket.socket, target: socket.socket, *, expect_masked: bool) -> None:
    try:
        while True:
            target.sendall(_recv_ws_frame(websocket, expect_masked=expect_masked))
    finally:
        try:
            target.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _proxy_pair(tcp_sock: socket.socket, ws_sock: socket.socket, *, client_side: bool) -> None:
    threads = [
        threading.Thread(target=_pipe_tcp_to_ws, args=(tcp_sock, ws_sock), kwargs={"mask": client_side}, daemon=True),
        threading.Thread(target=_pipe_ws_to_tcp, args=(ws_sock, tcp_sock), kwargs={"expect_masked": not client_side}, daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def _server_context(args: argparse.Namespace) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(args.certfile, args.keyfile)
    context.load_verify_locations(args.cafile)
    return context


def _client_context(args: argparse.Namespace) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=args.cafile)
    context.load_cert_chain(args.certfile, args.keyfile)
    context.check_hostname = True
    return context


def run_server(args: argparse.Namespace) -> None:
    context = _server_context(args)
    listener = socket.create_server((args.listen_host, args.listen_port), reuse_port=False)
    print(f"PermeantOS production WSS transport server listening on {args.listen_host}:{args.listen_port}", flush=True)
    while True:
        raw_client, _ = listener.accept()
        try:
            ws_sock = context.wrap_socket(raw_client, server_side=True)
            _server_handshake(ws_sock)
            target = socket.create_connection((args.target_host, args.target_port))
        except Exception:
            raw_client.close()
            raise
        threading.Thread(target=_proxy_pair, args=(target, ws_sock), kwargs={"client_side": False}, daemon=True).start()


def run_client(args: argparse.Namespace) -> None:
    context = _client_context(args)
    listener = socket.create_server((args.listen_host, args.listen_port), reuse_port=False)
    print(f"PermeantOS production WSS transport client listening on {args.listen_host}:{args.listen_port}", flush=True)
    while True:
        local, _ = listener.accept()
        try:
            raw_remote = socket.create_connection((args.remote_host, args.remote_port))
            ws_sock = context.wrap_socket(raw_remote, server_hostname=args.server_name)
            _client_handshake(ws_sock, args.server_name)
        except Exception:
            local.close()
            raise
        threading.Thread(target=_proxy_pair, args=(local, ws_sock), kwargs={"client_side": True}, daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PermeantOS production WSS/mTLS transport proxy")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    server = subparsers.add_parser("server")
    server.add_argument("--listen-host", default="0.0.0.0")
    server.add_argument("--listen-port", type=int, required=True)
    server.add_argument("--target-host", default="127.0.0.1")
    server.add_argument("--target-port", type=int, required=True)
    server.add_argument("--certfile", required=True)
    server.add_argument("--keyfile", required=True)
    server.add_argument("--cafile", required=True)

    client = subparsers.add_parser("client")
    client.add_argument("--listen-host", default="127.0.0.1")
    client.add_argument("--listen-port", type=int, required=True)
    client.add_argument("--remote-host", required=True)
    client.add_argument("--remote-port", type=int, required=True)
    client.add_argument("--server-name", default="permeant-target")
    client.add_argument("--certfile", required=True)
    client.add_argument("--keyfile", required=True)
    client.add_argument("--cafile", required=True)

    args = parser.parse_args()
    if args.mode == "server":
        run_server(args)
    else:
        run_client(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
