# QATQ PermeantOS Integration Feedback - 2026-06-22

This note records the first PermeantOS integration feedback for QATQ exact
before QATQ freezes its public API.

## Integration Slice

PermeantOS now has a Rust integration crate:

- crate: `permeant-qatq-migration`
- manifest schema: `permeantos.qatq-migration.v1`
- codec path: `qatq-exact`
- container label: `QATC-v2`
- current dependency in public CI: in-tree `qatq` compatibility shim
- intended source dependency for joint local validation: sibling `qatq` at
  commit `369d3ee`

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

The next AWS rerun for compression validation must use the pinned standalone
`qatq` crate from the QATQ repository, not the in-tree `qatq-compat`
compatibility container. Acceptance requires QATQ exact transferred bytes to be
less than or equal to raw bytes, with QATQ, raw, `zstd`, and `lz4` reported for
the same packed KV artifacts. Any run that still uses `qatq-compat` should be
recorded as an exact compatibility proof only.

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

- run PermeantOS against the sibling QATQ crate instead of the in-tree shim for
  the next AWS compression-validation pass;
- replace the exact wrapper in live migration with the standalone QATQ crate,
  then rerun the same AWS profile;
- exercise rollback by corrupting or deleting a QATQ artifact and proving target
  activation aborts with the source remaining authoritative;
- carry the standalone compression gate into the AWS live migration artifacts
  so the transferred bytes, not only local captures, are compared against raw,
  `zstd`, and `lz4`.
