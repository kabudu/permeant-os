# Production Transport Foundation

PermeantOS now has a production-shaped transport foundation in
`permeant-transport`. It is intended to replace ad-hoc SSH tunnels and
provider-specific HTTP bridges with a private, authenticated, bidirectional
streaming transport.

This release implements the reusable protocol core and cuts the AWS
real-runtime E2E runner over to the default production `wss://`/mTLS path. The
runner still supports `PERMEANT_MIGRATION_TRANSPORT=ssh-tunnel` as an explicit
compatibility fallback.

## Baseline

The baseline deployment target is private-network `wss://` with mutual TLS and
binary frames. This is the most deployable secure option across laptops,
workstations, cloud VMs, and managed runtimes.

Future high-throughput deployments can map the same session and frame model onto
QUIC, RDMA/UCX, or NIXL when the target runtime can keep the pipeline saturated.

## Transport Preference Ladder

Migration candidate systems should negotiate from a preference ladder rather
than assuming one transport exists everywhere:

| Priority | Mode | Use when |
| ---: | --- | --- |
| 100 | private `wss://` + mTLS + binary frames | default production path; deployable across most networks |
| 90 | QUIC + mTLS + binary frames | both endpoints support QUIC and lower latency matters |
| 50 | framed TCP + mTLS + binary frames | compatibility fallback for private networks without WebSocket or QUIC support |
| future | RDMA/UCX or NIXL | GPU-cluster deployments where runtime adapters can saturate high-throughput links |

Fallback must be explicit and recorded in migration evidence. PermeantOS should
never silently downgrade to plaintext transport or unauthenticated peers.

## Security Invariants

- Both endpoints must negotiate a production transport profile with binary
  framing enabled.
- The baseline profile requires mutual TLS at the channel layer.
- Fallback negotiation rejects candidates that disable mTLS or binary framing.
- Each session starts with a signed `SecureSessionHello` containing the session
  ID, endpoint role, node identity, peer identity, nonce, supported codecs, and
  frame limits.
- The signed hello rejects tampering before migration state is accepted.
- Frame payloads are bounded by negotiated `max_frame_bytes`.
- Payload CRC32 catches accidental corruption at the frame boundary.
- `(stream_id, frame_index)` replay tracking rejects duplicate frames inside the
  session validator.

The existing USXF encrypted envelope and graph-level signatures still protect
the state payloads. Production transport adds channel/session integrity,
boundedness, and replay resistance around the migration stream.

## Binary Frame Shape

Binary frames use a fixed 28-byte header:

| Field | Size | Purpose |
| --- | ---: | --- |
| magic | 4 | `PMT1` protocol marker |
| version | 2 | production transport version |
| kind | 1 | frame kind |
| flags | 1 | reserved control flags |
| stream_id | 4 | bidirectional logical stream |
| frame_index | 8 | monotonically increasing stream-local frame index |
| payload_len | 4 | bounded payload length |
| payload_crc32 | 4 | payload corruption check |

The payload follows immediately after the header. Control, graph, runtime-state,
and KV payload streams can share the same transport connection while remaining
separately ordered by `stream_id`.

## Performance Notes

The frame format is deliberately compact and parser-friendly:

- fixed-width big-endian header fields;
- no JSON parsing for hot-path frame boundaries;
- direct payload slicing after a single bounds check;
- independent stream IDs for bidirectional control/data flow;
- payload-size enforcement before allocation;
- codec negotiation in the session hello so raw, FP8, QATQ, or future codecs can
  be selected without changing the frame format.

## AWS Runner Cutover

The AWS runner now uses a stdlib Python production transport proxy to carry the
existing daemon byte stream over WSS/mTLS while the Rust daemon/client are moved
onto the native transport frame model incrementally:

1. The runner generates one-day ephemeral CA, server, and client certificates.
2. The server certificate includes `permeant-target` plus the target public IP
   in its SAN extension.
3. The target receives only `ca.crt`, `server.crt`, and `server.key`; the client
   private key stays local.
4. The AWS security group opens the WSS port only to the caller public IP.
5. The local proxy listens on `127.0.0.1:$PERMEANT_LOCAL_TUNNEL_PORT` and
   connects to the target WSS endpoint on
   `$PERMEANT_PRODUCTION_TRANSPORT_PORT` (`29443` by default).
6. `PERMEANT_MIGRATION_TRANSPORT=ssh-tunnel` remains available as an explicit
   fallback and is recorded in the run state when used.

Next transport work should move this proxy behavior into the Rust transport
crate, add richer backpressure/resume semantics, and benchmark QUIC or
NIXL/RDMA only after the runtime adapters can keep the transport saturated.

## AWS Validation

On June 20, 2026, the real AWS E2E runner completed a full production transport
run:

| Field | Value |
| --- | --- |
| AWS run ID | `20260620-224819` |
| Migration manifest | `migration-20260620-225636-64284-manifest.json` |
| Transport | production `wss://`/mTLS byte proxy, target port `29443` |
| Source runtime | local Apple Silicon MLX |
| Target runtime | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Transfer codec | experimental `qatq` |
| Transfer bytes | `6,294,528` of `49,545,216`; ratio `0.12704613095238096` |
| Fidelity | exact source/post-migration match for 16 generated tokens |
| Graph proof | 27-node Agent Memory Graph bound, resumed on target, returned to origin |
| Reverse import | vLLM target proof `sha256:cc27f81da25d629d36e5b680d8986acf385b867d334ce67515912f2fbc1cce2f`; MLX import proof `sha256:a4f0c01e5d02c9a07d6ca34fb95ce2d60232ea0a5583f88f0c45e61ae6a638d7` |
| Target activity | AWS proof `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c` |
| Return home | origin proof `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d` |
| Cleanup | instance, security group, and key pair deleted; cleanup verified at `2026-06-20T23:08:47Z` |

This proves the preferred default transport for the current validated
MLX-to-vLLM path. QATQ remains a lossy transfer codec, so the evidence claim is
bounded sampled tensor drift plus exact observed continuation for the configured
validation horizon, not bitwise tensor equality.

## Current Validation

Automated tests cover:

- signed session hello verification;
- signed hello tamper rejection;
- preferred transport selection;
- fallback to framed TCP/mTLS when higher-priority modes are unavailable;
- insecure downgrade rejection;
- binary frame encode/decode round trip;
- CRC mismatch rejection;
- oversized payload rejection;
- duplicate frame replay rejection;
- bidirectional stream IDs.

The AWS runner static tests also cover production-WSS defaults, mTLS
certificate generation/copying, WSS proxy startup, SSH fallback preservation,
target Cargo retry hardening, and cleanup trap ordering.
