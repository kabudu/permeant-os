# AWS Real-Runtime QATQ Exact Complex Proof - 2026-06-22

This report records the first successful real AWS end-to-end migration that
used the QATQ exact live transfer path for a complex Agent Memory Graph and a
significant live KV prefix.

## Summary

| Field | Value |
| --- | --- |
| Run ID | `20260622-150451` |
| Commit under test | `f30c046` |
| Source runtime | MLX live runtime |
| Target runtime | AWS vLLM |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| AWS target | `g4dn.xlarge`, `us-east-1d` |
| Migrated prefix | 1,920 tokens |
| Continuation horizon | 128 tokens |
| Transport | production `wss://`/mTLS tunnel |
| Transfer codec | `qatq` |
| QATQ storage strategy | `qatq-exact` |
| Agent graph hash | `sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b` |
| AWS cleanup | instance terminated, security group deleted, key pair deleted |

## What Was Proven

The run migrated a live MLX source prefix to an AWS vLLM target using
production transport and the exact QATQ transfer path. The target committed the
migrated KV state, seeded vLLM prefix-cache blocks, decoded the continuation,
exported the target decode boundary through the reverse runtime API, imported
that boundary back into the live MLX origin, resumed the Agent Memory Graph on
the AWS target, and then proved origin return-home continuation.

The continuation evidence was exact for all configured horizons:

| Comparison | 16 | 32 | 64 | 128 |
| --- | --- | --- | --- | --- |
| source vs post-migration | exact | exact | exact | exact |
| target baseline vs post-migration | exact | exact | exact | exact |

The fidelity report recorded:

- `success: true`
- `matches_source_exactly: true`
- `source_actual_token_count: 128`
- `post_migration_token_count: 128`
- `vllm_prefix_cache_seed_success: true`
- `written_layers: 24`
- `migration_target_block_count: 16`

The slot probe also passed across all target layers:

- `all_layers_slot_probe_match: true`
- `slot_probe_failure_count: 0`
- `max_key_abs_diff: 5.000000025123796e-09`
- `max_value_abs_diff: 5.000000025123796e-09`

## QATQ Evidence

The migration benchmark manifest was
`migration-20260622-151520-945-manifest.json`.

| Metric | Value |
| --- | --- |
| Transfer quantization | `qatq` |
| QATQ exact chunks | 384 |
| QATQ pass-through chunks | 0 |
| QATQ strategies | `{ "qatq-exact": 384 }` |
| Uncompressed bytes | 47,185,920 |
| Transferred bytes | 50,337,024 |
| Ratio | 1.0667805989583334 |

This proves the live migration path used QATQ exact containers for every
streamed chunk, with no pass-through fallback. It does not prove useful
compression yet. The current in-tree QATQ exact compatibility path is a
lossless typed container around exact `f32` little-endian bytes, so the payload
was about 6.7% larger due to exact-container overhead. The production QATQ
project still needs to replace this compatibility path with a mature exact
compression implementation before PermeantOS can claim a QATQ size benefit.

## Agent Activity And Return-Home Proof

The AWS target resumed the Agent Memory Graph and executed tool activity:

- `activity_continued: true`
- executed tools:
  - `tool:call:read-aws-quota`
  - `tool:call:publish-release`
- target proof hash:
  `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c`
- target post-resume graph hash:
  `sha256:f338313bf4876e92f3b31e07f9790e46629f1e8d01d8e93930a01e63c1eab7c8`

The live MLX origin then accepted the exported vLLM boundary:

- `reverse_runtime_imported: true`
- target prompt tokens: 1,920
- target generated tokens: 128
- origin advanced prompt tokens: 2,048
- reverse import proof hash:
  `sha256:d26fa884e009131be2a0b0ba9e8d0a55ec4d48c2061a5e2579c62c3f7166ff44`

Finally, the origin return-home proof passed:

- `round_trip_continued: true`
- origin post-graph hash:
  `sha256:35d2b4c784a1243604140b2d017343140fefb8ed3b2722952c8d05a99ba732f8`
- return-home proof hash:
  `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d`

## Commands

The source runtime was started with a clean continuation file and a 1,920-token
live prefix:

```sh
PERMEANT_MLX_EXPORTER_HOOK=/Users/kabudu/projex/permeant-os/adapters/mlx_live_runtime.py:provider \
PERMEANT_MLX_MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct \
PERMEANT_MLX_TARGET_SEQ_LEN=1920 \
PERMEANT_SOURCE_CONTINUATION_FILE=/tmp/permeant-source-continuation.json \
PERMEANT_SOURCE_CONTINUATION_USE_PREFILL_PROMPT=1 \
PERMEANT_SOURCE_CONTINUATION_MAX_TOKENS=128 \
PERMEANT_VLLM_CONTINUATION_MAX_TOKENS=128 \
PERMEANT_AGENT_GRAPH_CACHE_REF=kv:mlx-live:qatq-exact-aws-20260622 \
.mlx-source-venv/bin/python adapters/mlx_runtime_exporter.py --host 127.0.0.1 --port 29101
```

The AWS run used:

```sh
AWS_REGION=us-east-1 \
AWS_AZ=us-east-1d \
AWS_INSTANCE_TYPE=g4dn.xlarge \
PERMEANT_VALIDATION_PROFILE=qwen2.5-0.5b-long-horizon-aws \
PERMEANT_SEQ_LEN=1920 \
PERMEANT_CONTINUATION_MAX_TOKENS=128 \
PERMEANT_SOURCE_CONTINUATION_MAX_TOKENS=128 \
PERMEANT_FIDELITY_HORIZONS=16,32,64,128 \
PERMEANT_TRANSFER_QUANTIZATION=qatq \
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-complex-agent-graph/manifest.json \
PERMEANT_AGENT_ACTIVITY_RESUME=1 \
PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH=1 \
PERMEANT_AGENT_ACTIVITY_RETURN_HOME=1 \
PERMEANT_REVERSE_RUNTIME_IMPORT=1 \
PERMEANT_MIGRATION_TRANSPORT=production-wss \
scripts/aws-real-runtime-e2e.sh run
```

## Artifacts

Primary local artifacts were written under
`.permeant-e2e/aws/20260622-150451/`:

- `fidelity-analysis.json`
- `fidelity-horizons.json`
- `slot-probe-summary.json`
- `vllm-reverse-runtime-state.json`
- `mlx-reverse-import-report.json`
- `agent-activity-resume-report.json`
- `origin-roundtrip-workspace/reports/roundtrip/roundtrip-report.json`
- `target-logs/`

These runtime artifacts may include ephemeral connection metadata and are not
committed to source control.

## Follow-Up

The exact QATQ live path is now validated in a real AWS migration. Remaining
QATQ work belongs in the standalone QATQ project:

- rerun this AWS profile with the pinned external QATQ crate, not the in-tree
  `qatq-compat` container;
- provide true lossless compression for exact tensor payloads;
- compare QATQ against raw, `zstd`, and `lz4` for the same packed KV artifacts;
- accept a QATQ transfer-size reduction claim only if QATQ exact transferred
  bytes are less than or equal to raw bytes;
- record any future `qatq-compat` run as an exact compatibility proof only;
- keep PermeantOS fail-closed on checksum, dtype, shape, model, and task-probe
  mismatches.
