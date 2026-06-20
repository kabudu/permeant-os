# AWS Real-Runtime Production Transport Proof - 2026-06-20

This checkpoint validates the new default production transport path for the AWS
real-runtime runner. It replaces the previous SSH-tunneled daemon connection
with a production `wss://`/mTLS byte proxy while keeping the same real MLX
source, disposable AWS vLLM target, QATQ transfer codec, complex Agent Memory
Graph package, reverse runtime import, and return-home proof.

## Configuration

| Field | Value |
| --- | --- |
| AWS run ID | `20260620-224819` |
| Migration manifest | `migration-20260620-225636-64284-manifest.json` |
| Source runtime | local Apple Silicon MLX |
| Target runtime | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 2016 tokens |
| Transport | production `wss://`/mTLS byte proxy |
| Target WSS port | `29443` |
| Transfer codec | experimental `qatq` |
| Agent graph | 27 nodes, 25 edges, 4 packaged artifacts |

The runner generated one-day ephemeral CA, server, and client certificates. The
target received the CA and server certificate/key only; the client key remained
local. The AWS security group opened the WSS port only to the caller public IP.

## Result

The migration completed successfully over production WSS/mTLS:

- Capability exchange reached the target daemon through the WSS proxy.
- The encrypted USXF header was verified by the target.
- All 24 layers streamed and committed.
- The Agent Memory Graph package was bound into the staged KV transaction.
- vLLM prefix-cache seeding succeeded for 16 target blocks.
- Hash validation succeeded.
- Source/post-migration continuation matched exactly for 16 generated tokens.
- Reverse runtime export/import advanced the origin MLX runtime from the target
  decode boundary.
- AWS target-side graph activity continued and wrote a new artifact.
- The AWS-updated graph/report/artifact evidence returned to the origin, where
  origin-side work continued from the remote proof.

## Evidence

| Evidence | Value |
| --- | --- |
| Fidelity success | `true` |
| Alignment status | `aligned` |
| Graph hash | `sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b` |
| KV hash validation | `true` |
| Prefix-cache seeded blocks | `16` |
| Max complete exact horizon | `16` tokens |
| Target proof hash | `sha256:cc27f81da25d629d36e5b680d8986acf385b867d334ce67515912f2fbc1cce2f` |
| MLX reverse-import proof | `sha256:a4f0c01e5d02c9a07d6ca34fb95ce2d60232ea0a5583f88f0c45e61ae6a638d7` |
| AWS activity proof | `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c` |
| Return-home proof | `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d` |
| Cleanup verification | `2026-06-20T23:08:47Z` |

## Transfer Metrics

| Metric | Value |
| --- | ---: |
| Uncompressed bytes | 49,545,216 |
| Transferred bytes | 6,294,528 |
| Compression ratio | 0.12704613095238096 |
| Chunks sent | 384 |
| Average chunk bytes | 16,392 |
| Handshake time | 616.016459 ms |
| Header time | 222.567875 ms |
| Transfer time | 104,283.177625 ms |
| Commit time | 297,607.83575 ms |
| Total time | 414,148.584541 ms |
| Effective bandwidth | 0.00048287964700385205 Gbps |

This run is slower than the earlier SSH-tunneled QATQ round trip. The current
WSS proxy is intentionally conservative and carries the existing daemon byte
stream through a Python proxy. The result proves functional correctness and
secure-channel bootstrap for the preferred default transport; throughput work
belongs in the next native Rust transport/backpressure phase.

## QATQ Caveat

QATQ remained lossy at the tensor-slot level. The sampled slot probe reported:

- max key absolute delta: `0.006696999999999065`
- max value absolute delta: `0.000558149999999813`

Therefore the claim is not bitwise tensor equality. The validated claim is:
bounded sampled numeric drift, successful graph/KV/prompt alignment, and exact
observed continuation for the configured 16-token horizon.

## Cleanup

The runner deleted the disposable AWS instance, security group, and key pair.
The run state recorded cleanup verification at `2026-06-20T23:08:47Z`.

