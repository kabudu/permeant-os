# AWS Real-Runtime Transfer Quantization Comparison - 2026-06-20

This checkpoint compares two graph-attached AWS real-runtime E2E runs for the
same source, target, model, prefix length, and continuation horizon:

- Source runtime: local Apple Silicon MLX exporter
- Target runtime: AWS `g4dn.xlarge` running vLLM `0.23.0`
- Model: `Qwen/Qwen2.5-0.5B-Instruct`
- Prefix length: 2016 tokens
- Continuation horizon: 16 generated tokens
- Agent Memory Graph manifest:
  `/tmp/permeant-agent-graph-aws-proof/manifest.json`

## Runs

| Metric | Raw transfer | FP8 transfer |
| --- | ---: | ---: |
| AWS run ID | `20260620-153138` | `20260620-162019` |
| Manifest | `migration-20260620-153940-11152-manifest.json` | `migration-20260620-162809-25370-manifest.json` |
| Transfer quantization | `none` | `fp8` |
| Migration phase | `committed` | `committed` |
| Uncompressed bytes | 49,545,216 | 49,545,216 |
| Transferred bytes | 50,331,648 | 12,582,912 |
| Compression ratio | 1.015873 | 0.253968 |
| Chunks sent | 384 | 384 |
| Transfer time | 72,789.511 ms | 63,020.417 ms |
| Commit time | 311,836.559 ms | 315,134.429 ms |
| Total migration time | 396,126.853 ms | 389,689.972 ms |
| Source/post-migration continuation | exact, 16 tokens | exact, 16 tokens |
| Target-baseline/post-migration continuation | exact, 16 tokens | exact, 16 tokens |
| Graph alignment | aligned | aligned |
| KV alignment | aligned | aligned |
| Prompt alignment | aligned | aligned |
| Strict sampled slot equality | pass | fail, expected lossy deltas |
| Max sampled key delta | 0.0 | 0.0125 |
| Max sampled value delta | 0.0 | 0.0125 |
| Cleanup verified | yes | yes |

## Result

FP8 transfer reduced migrated payload bytes from 50,331,648 to 12,582,912,
which is a 75 percent reduction and approximately a 4x smaller transfer.

The measured transfer phase improved from 72.790 seconds to 63.020 seconds,
approximately a 13.4 percent reduction for this run. End-to-end migration time
improved only modestly, from 396.127 seconds to 389.690 seconds, because this
validation path is dominated by target commit/runtime attachment and vLLM
initialization effects rather than wire bytes alone.

The FP8 run still preserved the behavioral validation target for this scoped
test: graph, KV, and prompt alignment were all `aligned`; vLLM prefix-cache
seeding succeeded; and the post-migration continuation matched the MLX source
exactly for the configured 16-token horizon.

## Conclusion

For the validated MLX-to-AWS-vLLM configuration, FP8 transfer quantization is
functionally viable for the current short-horizon fidelity gate: the agent can
move, graph/KV binding remains aligned, and the generated continuation matches
the source exactly for 16 tokens.

The practical benefit in this run is payload reduction. The wall-clock benefit
is smaller because the current runner measures a cold, single-host disposable
path with heavy runtime setup and commit overhead. FP8 should become more
valuable in larger-context and steadier-state runs where transferred KV bytes
are a larger share of total latency.

The strict slot-probe equality check is not the right acceptance criterion for
lossy codecs: FP8 introduces small expected numeric deltas. For quantized runs,
acceptance should combine decode-fidelity gates, graph/KV/prompt alignment,
hash/transaction validation, and tolerance-aware slot summaries.
