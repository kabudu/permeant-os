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

This is not yet the real AWS migration trial requested by the integration
guide. It proves the local Rust API contract, manifest/checksum boundary, and
fail-closed restore behaviour.

Still required before QATQ API freeze acceptance:

- run PermeantOS against the sibling QATQ crate instead of the in-tree shim;
- pack real runtime-exported KV bytes into one or more QATQ exact bundles;
- transfer the encoded artifacts through AWS storage or the live migration
  channel;
- decode on the target, verify checksums, restore runtime tensors, and pass the
  target task-decision probe;
- exercise rollback by corrupting or deleting a QATQ artifact and proving target
  activation aborts with the source remaining authoritative;
- run QATQ size/throughput comparisons against `zstd` and `lz4` for the same
  packed migration bundle.
