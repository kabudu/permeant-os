# Production Transport Foundation

PermeantOS now has a production-shaped transport foundation in
`permeant-transport`. It is intended to replace ad-hoc SSH tunnels and
provider-specific HTTP bridges with a private, authenticated, bidirectional
streaming transport.

This release implements the reusable protocol core. It does not yet cut the AWS
E2E runner over from the current SSH tunnel path.

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

## Cutover Plan

1. Wrap the current daemon migration protocol in the new binary frame transport.
2. Add a `wss://` listener/client behind explicit CLI flags and certificate
   paths.
3. Require mTLS for non-loopback production transport.
4. Move the AWS runner from SSH tunnel transport to private `wss://` once the
   certificate bootstrap path is documented.
5. Add throughput and latency benchmarks against the current framed TCP path.
6. Evaluate QUIC and NIXL/RDMA only after the runtime adapters can keep the
   transport saturated.

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
