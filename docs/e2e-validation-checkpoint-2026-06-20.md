# Fresh E2E Validation Checkpoint - 2026-06-20

This checkpoint was run after the Phase 10 versioning-policy release to verify
the current PermeantOS migration path before continuing roadmap work.

## Commit Under Test

- Git commit at start of checkpoint: `7c49c13`
- Release tag at start of checkpoint: `v0.1.24-versioning-policy`
- Host: local macOS/aarch64 development machine

The checkpoint required two repeatability fixes on top of that commit:

- `adapters/mlx_runtime_exporter.py` now serves `GET /` and `GET /health` so
  readiness checks can verify that the local source exporter is reachable
  before provisioning AWS resources.
- `scripts/aws-real-runtime-e2e.sh` now handles
  `PERMEANT_TRANSFER_QUANTIZATION=none` without expanding an unset Bash array
  under `set -u`.

## Local E2E Results

The local daemon and simulated migration path passed on the current checkout.

| Path | Manifest | Result | Notes |
| --- | --- | --- | --- |
| Raw local `sim-migrate` | `migration-20260620-085008-9123-manifest.json` | pass | 512-token KV-only migration committed successfully. |
| FP8 local `sim-migrate --quant` | `migration-20260620-085005-9073-manifest.json` | pass | 512-token quantized transfer committed successfully with `compression_ratio: 0.25`. |
| Graph-bound local `sim-migrate --agent-graph-manifest` | `migration-20260620-085101-9414-manifest.json` | pass | Target accepted the Agent Memory Graph binding and committed the KV transaction. |
| Command-backed extractor/injector fixture roundtrip | `migration-20260620-085111-9537-manifest.json` | pass | Local command adapter boundary committed successfully. |

The local Agent Memory Graph export/import demo also passed before the
graph-bound migration. It verified artifact restore, signed-root/security
checks, side-effect audit, vector-memory equivalence, prompt hashes, and the
simulated KV hash.

## AWS Real-Runtime Readiness

The first preflight failed before provisioning because the local exporter was
not running and the AWS session had expired:

```text
.permeant-e2e/aws/20260620-085139/preflight-report.json
```

After refreshing AWS authentication and starting the local MLX exporter, the
preflight still failed until the exporter gained an unauthenticated health
endpoint. The final non-skipped preflight passed:

```text
.permeant-e2e/aws/20260620-122106/preflight-report.json
```

That report verified local commands, numeric runner configuration, transfer
quantization mode, the local `permeant-cli` build, the local source exporter,
AWS caller identity, the selected subnet, and the selected AMI.

## AWS Real-Runtime E2E Results

The first provisioned AWS run reached the migration step but failed before
starting the client command because the runner expanded an unset `quant_args`
array when transfer quantization was `none`:

```text
.permeant-e2e/aws/20260620-122126/
```

Cleanup completed and was verified for the failed run.

After the runner fix, the AWS real-runtime run completed and cleaned up:

```text
.permeant-e2e/aws/20260620-123542/
```

Key evidence from the successful run:

- Migration manifest: `migration-20260620-124343-64226-manifest.json`
- Model: `Qwen/Qwen2.5-0.5B-Instruct`
- Source runtime: live local MLX exporter
- Target runtime: disposable AWS NVIDIA host running vLLM
- Prefix length: 2016 tokens
- Layers migrated: 24
- KV chunks transferred: 384
- Uncompressed bytes: 49,545,216
- Transferred bytes: 50,331,648
- Migration phase status: `committed`
- Hash validation: pass
- Slot-probe validation: pass for every layer
- Cleanup verification: pass

The run proves that a fresh AWS host can be provisioned, receive the live MLX
KV cache, write matching vLLM slots, validate target hashes, commit the
migration, and clean up its disposable resources.

## Fidelity Follow-Up

The first successful AWS run did not prove source-exact continuation fidelity.
The post-migration continuation matched the target baseline exactly for the
16-token captured horizon, while source-vs-post-migration diverged after the
first shared token.

The analyzer reported:

- `hash_validation_success: true`
- `alignment.kv.status: aligned`
- `alignment.overall_status: partial`
- `matches_source_exactly: false`
- `matches_target_baseline_exactly: true`
- `migrated_decode_attachment_supported: false`

The root cause was a stale local source-continuation file copied to the target
before the live MLX exporter refreshed it for the current 2016-token prefill.
That stale file contained a one-token prompt, so vLLM could not compute full
prefix-cache hash blocks for the migrated prompt.

The follow-up fix refreshed and validated the source continuation before AWS
provisioning, then rewrote the source continuation on every live MLX extraction.
The follow-up AWS run completed successfully:

```text
.permeant-e2e/aws/20260620-144337/
```

Key evidence from the follow-up run:

- Migration manifest: `migration-20260620-145109-95872-manifest.json`
- Cleanup verification timestamp: `2026-06-20T15:02:55Z`
- `hash_validation_success: true`
- `matches_source_exactly: true`
- `matches_target_baseline_exactly: true`
- `migrated_decode_attachment_supported: true`
- `vllm_prefix_cache_seed_success: true`
- `vllm_prefix_cache_seeded_block_count: 16`
- `post_migration_prompt_token_count: 2016`
- `source_shared_prefix_token_count: 16`
- Slot-probe validation: pass for every layer

## Decision

The project now has fresh local E2E evidence and fresh AWS real-runtime
source-exact E2E evidence for KV migration, target hash validation, slot writes,
prefix-cache attachment, 16-token continuation fidelity, and cleanup
verification.
