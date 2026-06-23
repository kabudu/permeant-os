# QATQ PermeantOS Integration Feedback - 2026-06-22

This note records the first PermeantOS integration feedback for QATQ exact
before QATQ freezes its public API.

## Integration Slice

PermeantOS now has a Rust integration crate:

- crate: `permeant-qatq-migration`
- manifest schema: `permeantos.qatq-migration.v1`
- codec path: `qatq-exact`
- container label: `QATC-v2`
- current dependency in public CI: published `qatq` crate `0.1.1`
- development override path: sibling `qatq` checkouts only for explicit QATQ
  development runs

The crate keeps PermeantOS-specific migration metadata outside the codec:

- runtime, model, checkpoint, source, and target identities;
- dtype, byte order, layout, shape, URI, raw size, encoded size, raw checksum,
  and encoded checksum per artifact;
- fail-closed validation before target activation.

## What Passed Locally

The local Rust tests validate:

- native `f16` little-endian byte round trip through the exact typed API;
- manifest raw and encoded SHA-256 recording;
- encoded checksum mismatch rejection before decode;
- decoded dtype mismatch rejection;
- raw checksum mismatch rejection after decode;
- encoded size limit rejection before allocation-heavy decode;
- shape byte-count validation;
- schema and artifact-count validation.

Validation command:

```bash
cargo test -p permeant-qatq-migration --locked
```

## What Passed In AWS

PermeantOS also completed a real AWS MLX-to-vLLM migration using the exact QATQ
live transfer path:

- run: `20260622-150451`
- report:
  [`docs/aws-real-runtime-qatq-exact-complex-2026-06-22.md`](aws-real-runtime-qatq-exact-complex-2026-06-22.md)
- model: `Qwen/Qwen2.5-0.5B-Instruct`
- migrated prefix: 1,920 tokens
- continuation proof: exact 128-token source/post-migration and
  target-baseline/post-migration comparison
- transport: production `wss://`/mTLS
- agent graph: complex 27-node, 25-edge graph with four artifacts
- reverse path: vLLM reverse export, MLX reverse import, target graph activity,
  and origin return-home continuation all passed

QATQ-specific migration metrics:

- `qatq_compressed_chunks: 384`
- `qatq_pass_through_chunks: 0`
- `qatq_strategies: { "qatq-exact": 384 }`
- `uncompressed_bytes: 47185920`
- `transferred_bytes: 50337024`
- `compression_ratio: 1.0667805989583334`

This validates the live exact QATQ container path and fail-closed restore
boundary in a real AWS migration. It does not yet validate a QATQ compression
benefit: the current in-tree compatibility path preserves exact `f32`
little-endian bytes and adds container overhead, so it transferred more bytes
than raw. The standalone QATQ project still needs the production lossless
compression implementation before PermeantOS can claim QATQ reduces migration
size.

Compression validation must use the published standalone `qatq` crate from
crates.io, not the in-tree `qatq-compat` compatibility container. Acceptance
requires QATQ exact transferred bytes to be less than or equal to raw bytes,
with QATQ, raw, `zstd`, and `lz4` reported for the same packed KV artifacts.
Any run that still uses `qatq-compat` should be recorded as an exact
compatibility proof only.

## What Passed With Standalone QATQ

PermeantOS exported a full 1,920-token MLX KV bundle for
`Qwen/Qwen2.5-0.5B-Instruct` and benchmarked it with the standalone QATQ repo at
commit `3d223bc`. The packed bundle contained 48 tensors, one key and one value
capture for each of 24 layers, and was 47,185,920 raw f32 little-endian bytes.

Detailed report:
[`docs/qatq-standalone-compression-gate-2026-06-22.md`](qatq-standalone-compression-gate-2026-06-22.md)

Standalone compression results:

| Codec | Encoded bytes | Ratio vs raw f32 | Exact bits |
| --- | ---: | ---: | --- |
| `zstd-raw-f32le` | 20,713,110 | 0.4390 | yes |
| `lz4-raw-f32le` | 29,767,595 | 0.6309 | yes |
| `qatq-exact` | 14,097,901 | 0.2988 | yes |
| `qatq-exact-container` | 14,522,992 | 0.3078 | yes |

The standalone `competitive-compression` gate passed. A separate
`qatq encode-chunked` / `qatq decode` / `cmp` check also proved the QATC
container restored the packed bundle byte-for-byte.

## What Passed In AWS With Standalone QATQ

PermeantOS then replaced the live migration compatibility path with the
standalone QATQ crate and completed a real AWS MLX-to-vLLM migration:

- run: `20260622-194940`
- report:
  [`docs/aws-real-runtime-qatq-standalone-compression-2026-06-22.md`](aws-real-runtime-qatq-standalone-compression-2026-06-22.md)
- PermeantOS commit: `c0c7c8e`
- QATQ commit: `3d223bc`
- model: `Qwen/Qwen2.5-0.5B-Instruct`
- migrated prefix: 1,920 tokens
- continuation proof: exact 128-token source/post-migration and
  target-baseline/post-migration comparison
- transport: production `wss://`/mTLS
- reverse path: vLLM reverse export, MLX reverse import, target graph activity,
  and origin return-home continuation all passed

The live compression gate passed on the streamed block artifacts:

| Codec | Bytes | Ratio vs raw block baseline |
| --- | ---: | ---: |
| raw f32 block baseline | 50,331,648 | 1.0000 |
| standalone QATQ exact | 14,004,990 | 0.2782541513442993 |
| zstd raw-f32le | 20,405,381 | 0.4054184953371684 |
| lz4 raw-f32le | 28,739,217 | 0.5709969401359558 |

The live run used 384 `qatq-exact` chunks and zero QATQ pass-through chunks.

## API Feedback For QATQ

The typed tensor API shape is suitable for PermeantOS:

- `try_encode_qatq_exact_tensor_le(bytes_le, dtype)` is the right production
  encode boundary for native `f32`, `f16`, and `bf16` runtime exports.
- `decode_qatq_exact_tensor_le(payload)` returning `{ dtype, bytes_le }` is
  enough for PermeantOS to enforce manifest dtype and restore layout itself.
- PermeantOS should own shape, runtime identity, source/target identity, object
  URI, and activation policy rather than asking QATQ to own migration semantics.

QATQ should consider adding or freezing public helpers for:

- bounded QATC decode from bytes or readers with caller-provided limits for
  total values, chunk count, total encoded bytes, and per-chunk bytes;
- a stable way to report QATC chunk count, chunk dtype, total decoded bytes,
  and per-chunk encoded sizes without fully decoding first;
- an optional logical tensor label in QATC metadata only if it does not make
  QATC responsible for migration policy;
- streaming decode or chunk visitor APIs for large live migrations so
  PermeantOS can restore bundles without holding all decoded bytes at once.

## Current Boundaries

The real AWS exact-QATQ migration trial has passed for the Qwen2.5
MLX-to-vLLM profile. The local Rust API contract, manifest/checksum boundary,
and fail-closed restore behaviour are also covered by tests.

Still required before QATQ API freeze acceptance:

- exercise rollback by corrupting or deleting a QATQ artifact and proving target
  activation aborts with the source remaining authoritative;
- broaden standalone-QATQ live validation to additional models and runtime
  adapters.
