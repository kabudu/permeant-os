# Fidelity Horizon Suite

PermeantOS can compare source, target-baseline, and post-migration
continuations across multiple decode horizons. This makes longer-horizon
fidelity checks repeatable without changing the real-runtime analyzer format.

Run the suite against a source continuation file and a target probe:

```bash
scripts/analyze-fidelity-horizons.py \
  --source /tmp/permeant-source-continuation.json \
  --probe .permeant-e2e/aws/<run-id>/vllm-runtime-probe.json \
  --horizons 16,32,64,128 \
  --markdown-out .permeant-e2e/aws/<run-id>/fidelity-horizons.md \
  --pretty
```

The target probe supplies the latest `generate_continuation` event and, when
available, the latest `baseline_continuation` event. A post-migration
continuation JSON file may also be supplied directly with `--post`.

The JSON output includes:

- `schema_version`: currently `permeantos-fidelity-horizon-suite-v0`.
- `horizons`: the requested token horizons.
- `max_complete_exact_horizon`: the largest horizon where every available
  comparison is exact.
- `comparisons`: per-pair reports for `source_vs_post_migration` and, when
  available, `baseline_vs_post_migration`.

Each horizon reports:

- `status`: `exact`, `diverged`, or `insufficient_tokens`.
- `first_mismatch_index`: the first token mismatch before that horizon, when
  present.
- available token counts for the expected and actual continuations.

AWS runner integration:

```bash
PERMEANT_CONTINUATION_MAX_TOKENS=64 \
PERMEANT_FIDELITY_HORIZONS=16,32,64 \
scripts/aws-real-runtime-e2e.sh run
```

The runner still defaults to `16` generated continuation tokens to preserve the
current low-cost validation path. When a larger continuation length is
requested, it writes:

- `fidelity-horizons.json`
- `fidelity-horizons.md`

## Cost-Balanced Long-Horizon Strategy

Long-horizon validation should be separated into three evidence tiers:

1. **Captured local analysis**: run the horizon analyzer against existing source
   and target probe artifacts. This is free and catches reporting or token
   comparison issues, but it does not create new runtime evidence.
2. **True local or LAN real-runtime validation**: run a real MLX source and a
   real vLLM target without disposable AWS provisioning. This is strong evidence
   for long continuation stability when the target is a real GPU vLLM runtime.
   On an Apple Silicon laptop, MLX can be local but vLLM typically needs a
   Linux/NVIDIA host, so a nearby workstation, homelab GPU, or manually managed
   GPU box is the practical low-cost target.
3. **Sparse AWS confirmation**: after a long-horizon local/LAN run passes, run
   one disposable AWS proof for the most important profile to confirm that the
   production `wss://`/mTLS transport, cloud target bootstrap, cleanup, and
   remote runtime behavior still hold.

The default long-horizon candidate should use:

```bash
PERMEANT_VALIDATION_PROFILE=qwen2.5-0.5b-long-horizon-aws \
PERMEANT_CONTINUATION_MAX_TOKENS=128 \
PERMEANT_FIDELITY_HORIZONS=16,32,64,128 \
PERMEANT_SEQ_LEN=1920 \
PERMEANT_VLLM_MAX_MODEL_LEN=2048
```

The shorter migrated prefix leaves enough context-window headroom for 128
continuation tokens and avoids the earlier false-failure mode where target-side
tokenization exhausted the context window before the validation horizon.

## Validated Long-Horizon Run

The `qwen2.5-0.5b-long-horizon-aws` profile completed on 2026-06-21 with:

- AWS run ID `20260621-052744`.
- Manifest `migration-20260621-053602-9938-manifest.json`.
- 1920-token migrated prefix and 128 generated continuation tokens.
- Production `wss://`/mTLS transport and QATQ transfer.
- Exact `source_vs_post_migration` and `baseline_vs_post_migration` matches at
  16, 32, 64, and 128 tokens.
- `max_complete_exact_horizon` of 128.

See `docs/aws-real-runtime-long-horizon-2026-06-21.md` for hashes, QATQ deltas,
round-trip graph activity, reverse import, and AWS cleanup evidence.

Current limitations:

- The suite evaluates captured continuation artifacts; it does not itself
  provision cloud resources or generate new model outputs.
- A horizon can only pass when both sides generated at least that many tokens.
- Real-runtime claims still require controlled runs with the requested
  continuation length, model/runtime versions, prompt length, and hardware
  profile recorded.
