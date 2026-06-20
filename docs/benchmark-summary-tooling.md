# Benchmark Summary Tooling

PermeantOS migration runs emit `migration-*-manifest.json` files. The summary
tool converts a manifest batch into structured JSON and an optional Markdown
table for papers, release notes, and scheduled validation records.

Run it against one or more manifest files or directories:

```bash
scripts/summarize-benchmark-manifests.py benchmark-manifests/run-2026-06-20 \
  --markdown-out benchmark-manifests/run-2026-06-20/summary.md
```

The JSON output includes:

- `schema_version`: currently `permeantos-benchmark-summary-v0`.
- `groups`: aggregate counts and timing summaries grouped by sequence length
  and transfer quantization.
- `failure_records`: failed runs with source manifest path, phase status,
  failure class, and error message.
- `paper_table_rows`: compact rows suitable for Markdown or LaTeX table
  generation.

Failure runs are counted and reported, but they are excluded from timing
medians and bandwidth summaries. This keeps failed validation attempts visible
without polluting success-path performance numbers.

Current scope:

- Local and cloud-run manifests that follow the existing migration manifest
  shape.
- Grouping by `sequence_length` and `transfer_quantization`.
- Failed graph binding and commit phases recorded through manifest
  `phase_status`.

Current limitations:

- The tool summarizes existing runs; it does not provision infrastructure or
  execute benchmarks.
- Paper-ready numbers still require controlled real-runtime batches, including
  repeated runs, hardware/runtime version records, and model/runtime warm-state
  notes.
- Adaptive codec experiments such as FP8, TurboQuant-style, and
  Quaternion-Augmented TurboQuant candidates still need runtime implementations
  before they can produce comparable manifest batches.
