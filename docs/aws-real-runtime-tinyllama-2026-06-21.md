# AWS TinyLlama Real-Runtime E2E Proof - 2026-06-21

This checkpoint is the first non-Qwen model-family AWS real-runtime proof. It
uses raw transfer only; QATQ was intentionally disabled while QATQ is perfected
as a separate codec project.

| Field | Value |
| --- | --- |
| Run ID | `20260621-085222` |
| Profile | `tinyllama-1.1b-chat-mlx-vllm` |
| Model | `TinyLlama/TinyLlama-1.1B-Chat-v1.0` |
| Runtime path | local MLX to AWS vLLM |
| AWS instance | `g4dn.xlarge` |
| Transport | production `wss://`/mTLS |
| Transfer quantization | `none` |
| Migrated prefix | 1984 tokens |
| Target max context | 2048 tokens |
| Manifest | `migration-20260621-090036-99513-manifest.json` |
| Cleanup | verified at `2026-06-21T09:14:44Z` |

## Result

The run completed the full E2E path:

- live TinyLlama KV extraction from the local MLX source;
- raw tensor transfer over production WSS/mTLS;
- 22 TinyLlama layers written into the AWS vLLM runtime;
- Agent Memory Graph package bound into the same staged transaction;
- vLLM prefix-cache attachment for the migrated block table;
- two-phase commit;
- target vLLM reverse runtime export;
- origin MLX reverse runtime import;
- target-side Agent Memory Graph activity continuation;
- origin return-home proof over the AWS-updated graph and artifact.

Important proof hashes:

| Proof | Hash |
| --- | --- |
| Target reverse runtime export | `sha256:6178a207ab5f60be0b76398e06fec171897d51e9d71b258b0bb2db32e1e4a3ec` |
| Origin MLX reverse import | `sha256:040a43c1e5001989a496054256da63702758a5fad7dddbd4e250d5939622a84b` |
| Target graph activity continuation | `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c` |
| Origin return-home continuation | `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d` |

## Fidelity

`fidelity-analysis.json` reports:

- `success=true`
- `hash_validation_success=true`
- `written_layers=22`
- `vllm_prefix_cache_seed_success=true`
- `vllm_prefix_cache_seeded_block_count=16`
- `matches_target_baseline_exactly=true`
- `matches_source_exactly=false`

The slot probe is exact within float comparison tolerance:

- `all_layers_slot_probe_match=true`
- `slot_probe_failure_count=0`
- `max_key_abs_diff=5.000000025123796e-09`
- `max_value_abs_diff=5.000000025123796e-09`

The source/post-migration text mismatch starts at token index `0`: the source
continuation starts with `build`, while the vLLM baseline and post-migration
continuation start with a leading-space ` build`. The target baseline and
post-migration continuation match exactly for the configured 16-token horizon,
so this run proves structural migration, target-runtime reuse, and graph
continuation for TinyLlama. It does not claim source-exact cross-runtime decode
parity for MLX vs vLLM on this model.

## Engineering Fixes

The run found and fixed two validation-harness issues before the successful
attempt:

- model-family profiles now carry explicit cache geometry; TinyLlama uses
  22 layers, 32 query heads, 4 KV heads, head dimension 64, hidden size 2048,
  and 256-token PermeantOS transfer blocks;
- AWS target setup now waits on actual apt/dpkg lock files with `fuser`, rather
  than treating the harmless `unattended-upgrade-shutdown --wait-for-signal`
  helper as an active package-manager lock holder.

## Scope

This is a broader model-family proof, not a longer-horizon proof. The
continuation horizon for this run was 16 target tokens. The Qwen2.5 long-horizon
AWS profile remains the current 128-token exact-fidelity proof.
