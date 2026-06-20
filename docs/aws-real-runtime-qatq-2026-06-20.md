# AWS Real-Runtime QATQ E2E - 2026-06-20

This checkpoint validates the experimental Quaternion-Augmented TurboQuant
(`qatq`) transfer codec on the real MLX-to-AWS-vLLM migration path.

The codec implemented for this checkpoint is an experimental
quaternion-grouped int4 transfer codec: each consecutive group of four KV
values is treated as a quaternion lane and packed into signed int4 coefficients
with a chunk-level scale. It is a lossy transfer codec. The relevant validation
question is therefore whether it reduces payload bytes while preserving
post-migration continuation fidelity, graph/KV alignment, and bounded numeric
slot deltas.

## Run Configuration

```bash
PERMEANT_TRANSFER_QUANTIZATION=qatq \
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-qatq-complex-agent-graph/manifest.json \
  scripts/aws-real-runtime-e2e.sh preflight

PERMEANT_TRANSFER_QUANTIZATION=qatq \
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-qatq-complex-agent-graph/manifest.json \
  scripts/aws-real-runtime-e2e.sh run
```

| Field | Value |
| --- | --- |
| Preflight run ID | `20260620-173005` |
| AWS run ID | `20260620-173045` |
| Migration manifest | `migration-20260620-173846-50882-manifest.json` |
| Source runtime | local MLX exporter on Apple Silicon |
| Target runtime | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 2016 tokens |
| Transfer quantization | `qatq` |
| Agent Memory Graph | complex 27-node package |
| Graph hash | `sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b` |

## Compression Result

| Run | Mode | Transferred bytes | Ratio vs raw f32 | Transfer time | Total time |
| --- | --- | ---: | ---: | ---: | ---: |
| Raw complex graph | `none` | 50,331,648 | 1.015873 | 71,568.635 ms | 426,187.141 ms |
| Raw minimal graph | `none` | 50,331,648 | 1.015873 | 72,789.511 ms | 396,126.853 ms |
| FP8 minimal graph | `fp8` | 12,582,912 | 0.253968 | 63,020.417 ms | 389,689.972 ms |
| QATQ complex graph | `qatq` | 6,294,528 | 0.127046 | 62,548.267 ms | 386,467.572 ms |

QATQ reduced transferred bytes by:

- 87.49 percent relative to the raw graph-attached payload;
- 49.98 percent relative to the previous FP8 graph-attached payload.

The transfer-time improvement is much smaller than the byte reduction because
this cold-host AWS path is dominated by target setup, vLLM startup, runtime
attachment, and commit/probe overhead rather than by network throughput alone.

## Fidelity Result

The fidelity analyzer reported:

- `success: true`
- `matches_source_exactly: true`
- `matches_target_baseline_exactly: true`
- `migrated_decode_attachment_supported: true`
- `alignment.overall_status: aligned`
- `alignment.graph.status: aligned`
- `alignment.kv.status: aligned`
- `alignment.prompt.status: aligned`
- `vllm_prefix_cache_seed_success: true`
- exact source/post-migration continuation for the configured 16 generated
  tokens

The slot-probe summary reported expected lossy numeric deltas:

- `all_layers_slot_probe_match: false`
- `slot_probe_failure_count: 17`
- `max_key_abs_diff: 0.006696999999999065`
- `max_value_abs_diff: 0.000558149999999813`

The first sampled mismatch was a key value changing from `-18.571428` to
`-18.578125`, a delta of `0.006696999999999065`. The continuation still matched
exactly for the validated horizon.

## Cleanup

The runner cleanup completed at `2026-06-20T17:50:14Z`. Independent AWS sweeps
after the script exited returned empty result sets for:

- active/stopped EC2 instances tagged `Project=permeant-os`;
- `permeantos-real-e2e-*` security groups;
- `permeantos-real-e2e-*` key pairs.

The local MLX exporter was stopped and port `29101` was no longer listening.

## Conclusion

For this validated MLX-to-vLLM configuration, experimental QATQ produced the
best payload compression measured so far: about 8x smaller than raw f32 transfer
and about 2x smaller than FP8. It is not numerically lossless: sampled KV slots
show bounded lossy deltas. It did preserve the observable migration target for
this run: graph/KV/prompt alignment and exact 16-token source/post-migration
continuation fidelity.

The next useful validation is a longer continuation horizon and a larger-context
run, because 16 tokens proves compatibility for this checkpoint but does not yet
bound longer-tail generation drift.
