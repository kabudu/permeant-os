# QATQ Production Decision Live Migration Evidence - 2026-06-21

This checkpoint wires PermeantOS live migration directly to the sibling QATQ
phase-2 lossless production decision API. The live `sim-migrate` path now calls
`try_encode_phase2_lossless_decision_with_config`, sends per-chunk storage
metadata, and restores either compressed QATQ payloads or raw f32le
pass-through payloads on the daemon before commit validation.

## Implementation

- `--transfer-codec qatq` now uses QATQ phase-2 lossless decisions instead of
  the older experimental int4 helper.
- Each payload chunk carries explicit codec metadata:
  - `storage=qatq-phase2` for compressed QATQ containers.
  - `storage=raw-f32le-pass-through` when QATQ selects raw f32le bypass.
- Migration manifests now include QATQ decision counters and strategy counts.
- The daemon rejects QATQ chunks that omit codec metadata or declare an
  unsupported storage representation.

## Live Migration Results

| Run | Source data | Seq | Layers | Chunks | Decision path | Transferred bytes | Ratio | Commit |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| `migration-20260621-192111-40451` | deterministic mock KV | 512 | 4 | 16 | 16 compressed, 0 pass-through | 1,221,318 | 0.5824 | passed |
| `migration-20260621-192230-41693` | GPT-2 f32le captures | 64 | 1 | 2 | 0 compressed, 2 pass-through | 393,216 | 1.0000 | passed |

Compressed strategy histogram for `migration-20260621-192111-40451`:

| Strategy | Chunks |
| --- | ---: |
| `byte-plane-rle` | 10 |
| `byte-plane-blocks` | 6 |

The GPT-2 run used the command-backed extractor with real QATQ capture files:

- `gpt2-seq64-layer0-key.f32le`
- `gpt2-seq64-layer0-value.f32le`

It exercised the production raw f32le pass-through path through the same live
network protocol and commit validation as normal migration.

## Validation

- `cargo fmt --check`
- `cargo check`
- `cargo test`
- Live QATQ compressed migration:
  `cargo run -p permeant-cli -- sim-migrate --target-addr 127.0.0.1:19099 --seq-len 512 --transfer-codec qatq`
- Live QATQ pass-through migration using GPT-2 f32le captures and
  `PERMEANT_EXTRACTOR_MODE=json_command`.

Both live migrations reached `phase_status=committed` and the daemon logged
`Validation passed. Committing migration state.`
