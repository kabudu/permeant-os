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

Current limitations:

- The suite evaluates captured continuation artifacts; it does not itself
  provision cloud resources or generate new model outputs.
- A horizon can only pass when both sides generated at least that many tokens.
- Real-runtime claims still require controlled runs with the requested
  continuation length, model/runtime versions, prompt length, and hardware
  profile recorded.
