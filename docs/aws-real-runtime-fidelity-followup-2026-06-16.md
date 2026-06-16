# AWS real-runtime fidelity follow-up (2026-06-16)

This follow-up reran the corrected 24-layer live migration path against a real AWS `vLLM` target to answer two questions:

1. Does the cold-start path succeed reliably with a longer runtime-hook timeout?
2. Is the remaining source/target continuation divergence caused by FP8 transfer quantization?

## Code changes validated in this follow-up

- `crates/cli/src/main.rs`
  - normalize live MLX KV tensors from `[1, kv_heads, seq_len, head_dim]` to canonical `[seq_len, kv_heads, head_dim]`
  - record `n_q_heads` from the configured model instead of hardcoding `8` in success manifests
- `adapters/vllm_http_runtime_hook.py`
  - raise the default cold-path runtime timeout from `30s` to `900s`

## Real target host

- Cloud: AWS EC2
- Region: `us-east-1`
- Instance type: `g4dn.xlarge`
- GPU: NVIDIA Tesla T4
- Target runtime: `vLLM 0.23.0`
- Model: `Qwen/Qwen2.5-0.5B-Instruct`

## Run A: corrected live migration with FP8 transfer

Manifest:
- `migration-20260616-134821-80010-manifest.json`

Key results:
- `success: true`
- `layers: 24`
- `transfer_quantization: fp8`
- `chunks_sent: 384`
- `transferred_bytes: 12582912`
- `total_time_ms: 106154.306208`

Target runtime probe result:
- target initialized a real `vLLM` runtime
- all `24` layers were written into live KV caches
- continuation generated successfully
- divergence remained at token index `15`

Source vs target continuation:
- expected final token text: `For`
- actual final token text: `A`

## Run B: corrected live migration with no transfer quantization

Manifest:
- `migration-20260616-151833-27980-manifest.json`

Key results:
- `success: true`
- `layers: 24`
- `n_q_heads: 14`
- `transfer_quantization: none`
- `chunks_sent: 384`
- `transferred_bytes: 50331648`
- `total_time_ms: 379837.03454200004`

Target runtime probe result:
- target initialized a real `vLLM` runtime
- all `24` layers were written into live KV caches
- continuation generated successfully
- divergence remained at token index `15`

Source vs target continuation:
- expected final token text: `For`
- actual final token text: `A`

## Comparison

### What improved

- The cold path now succeeds on a fresh real target because the runtime hook is allowed to survive `vLLM` initialization and warmup.
- The migration manifests now correctly report `n_q_heads: 14` for this Qwen model.
- Both the quantized and non-quantized real-runtime runs complete successfully end to end.

### What did not change

- The continuation mismatch is identical with and without transfer quantization.
- The first mismatch still occurs at token index `15`.
- That means the remaining fidelity gap is not explained by FP8 transfer compression.

## Verdict

`permeantOS` now demonstrates:
- successful encrypted cross-host migration
- successful real target runtime initialization
- successful registration of all 24 migrated layers into live `vLLM` KV caches
- successful post-migration continuation generation on the real target

But it still does **not** demonstrate bit-faithful continuation fidelity.

The next debugging target is therefore the semantic/layout/runtime boundary rather than transport compression. The most likely remaining areas are:
- canonical-to-target KV layout semantics beyond simple shape compatibility
- block ordering or per-layer placement subtleties in the live `vLLM` cache writer
- runtime state outside the migrated KV tensors that still affects the next-token decision

## Next run instrumentation

The next real run should compare three continuations side by side:

- the source continuation from the MLX host
- a target baseline continuation captured before migration
- the target continuation generated after migration

To support that, the target runtime now:

- captures a baseline continuation during real runtime initialization
- records richer per-layer cache-write summaries in the probe output
- exposes a lightweight analyzer script at `adapters/analyze_real_runtime_fidelity.py`

Example usage:

```bash
python3 adapters/analyze_real_runtime_fidelity.py \
  --manifest migration-20260616-151833-27980-manifest.json \
  --probe /tmp/permeant_vllm_probe.json \
  --pretty
```

The analyzer reports:

- migration success
- verification success
- number of target layers written
- first mismatch index versus the source continuation
- first mismatch index versus the target baseline continuation
- whether post-migration output exactly matches the target baseline

If a future run shows the post-migration continuation remaining close to the target baseline rather than the source, that will strongly suggest we still need to migrate additional runtime state beyond KV cache tensors.
