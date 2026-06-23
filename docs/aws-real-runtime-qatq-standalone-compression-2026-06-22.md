# AWS Real-Runtime Standalone QATQ Compression Proof - 2026-06-22

This report records the first real AWS end-to-end PermeantOS migration using
the standalone QATQ crate in the live transfer path, with continuation fidelity
and live compression-gate evidence.

## Summary

| Field | Value |
| --- | --- |
| Run ID | `20260622-194940` |
| PermeantOS commit under test | `c0c7c8e` |
| QATQ commit under test | `3d223bc` |
| Source runtime | MLX live runtime |
| Target runtime | AWS vLLM |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| AWS target | `g4dn.xlarge`, `us-east-1d` |
| Migrated prefix | 1,920 tokens |
| Continuation horizon | 128 tokens |
| Transport | production `wss://`/mTLS tunnel |
| Transfer codec | standalone `qatq` crate |
| QATQ storage strategy | `qatq-exact` |
| Agent graph hash | `sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b` |
| AWS cleanup | instance terminated, security group deleted, key pair deleted |

The target build log showed the standalone crate path:

```text
Compiling qatq v0.1.0 (/home/ubuntu/qatq)
```

The AWS runner copied the sibling QATQ repository to `/home/ubuntu/qatq` before
building PermeantOS, so this run did not use the in-tree `qatq-compat`
container.

## Continuation Evidence

The migration completed successfully and wrote
`migration-20260622-195927-7216-manifest.json`.

Fidelity summary:

- `success: true`
- `matches_source_exactly: true`
- `matches_target_baseline_exactly: true`
- `source_actual_token_count: 128`
- `post_migration_token_count: 128`
- `vllm_prefix_cache_seed_success: true`
- `written_layers: 24`

The fidelity horizon suite passed at every configured horizon:

| Comparison | 16 | 32 | 64 | 128 |
| --- | --- | --- | --- | --- |
| source vs post-migration | exact | exact | exact | exact |
| target baseline vs post-migration | exact | exact | exact | exact |

The slot probe also passed:

- `all_layers_slot_probe_match: true`
- `slot_probe_failure_count: 0`
- `max_key_abs_diff: 5.000000025123796e-09`
- `max_value_abs_diff: 5.000000025123796e-09`

## Live Compression Gate

The runner enforced `permeantos-qatq-live-compression-gate-v0` after fidelity
analysis and before reverse import or graph continuation. The gate compared the
actual transferred QATQ payload against raw f32, `zstd`, and `lz4` over the same
streamed block artifacts.

| Metric | Value |
| --- | ---: |
| Raw f32 block baseline bytes | 50,331,648 |
| Standalone QATQ transferred bytes | 14,004,990 |
| zstd raw-f32le bytes | 20,405,381 |
| lz4 raw-f32le bytes | 28,739,217 |
| QATQ ratio vs raw block baseline | 0.2782541513442993 |
| zstd ratio vs raw block baseline | 0.4054184953371684 |
| lz4 ratio vs raw block baseline | 0.5709969401359558 |
| QATQ compressed chunks | 384 |
| QATQ pass-through chunks | 0 |

Gate checks:

| Check | Result |
| --- | --- |
| migration success | pass |
| uses `qatq-exact` | pass |
| no QATQ pass-through chunks | pass |
| QATQ bytes <= raw bytes | pass |
| QATQ bytes <= zstd bytes | pass |
| QATQ bytes <= lz4 bytes | pass |

The manifest field `uncompressed_bytes` is 47,185,920, which is the logical
unpadded 1,920-token KV size. The live compression gate uses
`raw_f32le_baseline_bytes` of 50,331,648 because the streamed runtime artifacts
are block-padded to the vLLM block layout. QATQ, zstd, and lz4 were all measured
against that same block-padded live transfer artifact set.

## Reverse And Return-Home Proof

The target exported the decode boundary through the vLLM reverse runtime API,
and the live MLX origin imported it:

- `reverse_runtime_imported: true`
- target generated tokens: 128
- origin advanced prompt tokens: 2,048
- reverse import proof hash:
  `sha256:d26fa884e009131be2a0b0ba9e8d0a55ec4d48c2061a5e2579c62c3f7166ff44`
- target proof hash:
  `sha256:5c189979b52e35b9d3c434b6dc9dec1a075972137242fd94f171b7a096cec302`

The Agent Memory Graph resumed on the AWS target:

- `activity_continued: true`
- executed tools:
  - `tool:call:read-aws-quota`
  - `tool:call:publish-release`
- target activity proof hash:
  `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c`

The origin return-home proof also passed:

- `round_trip_continued: true`
- return-home proof hash:
  `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d`

## Commands

The run used:

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
PERMEANT_QATQ_STANDALONE_PATH=/Users/kabudu/projex/qatq \
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
`.permeant-e2e/aws/20260622-194940/`:

- `fidelity-analysis.json`
- `fidelity-horizons.json`
- `qatq-live-compression-gate.json`
- `slot-probe-summary.json`
- `vllm-reverse-runtime-state.json`
- `mlx-reverse-import-report.json`
- `agent-activity-resume-report.json`
- `origin-roundtrip-workspace/reports/roundtrip/roundtrip-report.json`
- `target-logs/`

Runtime artifacts can include ephemeral connection metadata and are not
committed to source control.

## Conclusion

This run satisfies the corrected QATQ acceptance gate for PermeantOS:

- standalone QATQ crate used in the live AWS migration path;
- exact 128-token continuation after migration;
- QATQ transferred fewer bytes than raw, `zstd`, and `lz4` on the same streamed
  live artifacts;
- no pass-through QATQ chunks;
- reverse runtime import and origin return-home continuation both passed;
- AWS cleanup completed and was independently verified.
