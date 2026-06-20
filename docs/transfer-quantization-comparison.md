# Transfer Quantization Comparison

PermeantOS can compare paired migration manifests for raw and transfer-quantized
KV-cache runs. The comparison tooling is intended for real-runtime benchmark
batches where each candidate quantization mode is run against the same model,
sequence length, dtype, source quantization, and target device as the raw
baseline.

Generate a larger-context matrix with raw and FP8 points:

```bash
scripts/plan-context-benchmarks.py \
  --quantization-modes none,fp8 \
  --markdown-out benchmark-manifests/context-matrix.md \
  --env-out benchmark-manifests/context-matrix.env
```

After running the generated environment blocks with
`scripts/aws-real-runtime-e2e.sh run`, compare the saved manifests:

```bash
scripts/compare-transfer-quantization.py benchmark-manifests/<run-label> \
  --markdown-out benchmark-manifests/<run-label>/transfer-quantization.md
```

The JSON output uses schema version
`permeantos-transfer-quantization-comparison-v0`. Each comparison group is
keyed by:

- `sequence_length`
- `model_identity`
- `model_architecture`
- `dtype`
- `source_quantization`
- `target_device`

The default baseline mode is `none`. Non-baseline modes such as `fp8` are only
marked `comparable` when both the baseline and candidate have at least one
successful manifest in the same group. Failed manifests are counted as failures
but excluded from performance medians.

## Fidelity Evidence

Performance comparison is not the same as fidelity validation. By default the
tool reports transport and total-time deltas only.

To require explicit decode-fidelity evidence on both baseline and candidate
manifests, pass a
minimum horizon:

```bash
scripts/compare-transfer-quantization.py benchmark-manifests/<run-label> \
  --require-fidelity-horizon 64 \
  --markdown-out benchmark-manifests/<run-label>/transfer-quantization.md
```

With `--require-fidelity-horizon`, candidate modes are marked:

- `comparable` when both modes have performance data and fidelity evidence at or
  above the required horizon.
- `performance_only` when both modes have successful performance data but one
  or both lack sufficient fidelity evidence.
- `insufficient_data` when the baseline or candidate has no successful paired
  run.

The tool recognizes fidelity evidence embedded in a manifest as either
`fidelity_max_complete_exact_horizon`, `max_complete_exact_horizon`, or
`fidelity_horizon_summary.max_complete_exact_horizon`. Current AWS runner output
still writes fidelity horizon reports beside the manifests, so publishable
real-runtime quantization claims should either embed that horizon summary into
the manifest batch record or cite the matching fidelity report alongside the
comparison table.

## Limitations

- The tool compares captured benchmark records; it does not provision cloud
  infrastructure or run migrations.
- A `comparable` result means the records are paired by manifest metadata. It
  does not imply statistical significance.
- Network, instance, model-loading, and cold-start effects still need to be
  controlled by the benchmark run plan.
- Real-runtime fidelity claims require matching continuation artifacts analyzed
  with `scripts/analyze-fidelity-horizons.py`.
