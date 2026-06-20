# AWS Real-Runtime Complex Agent E2E - 2026-06-20

This checkpoint validates a complex Agent Memory Graph package on the real
MLX-to-AWS-vLLM migration path. It is stronger than the earlier minimal graph
proof because the migrated graph includes conversation state, artifacts,
memory, retrieval evidence, credential rebinding, and pending tool-call policy.

## Package Under Test

The package was generated locally with:

```bash
python3 examples/agent-memory-graph/local_agent.py complex-demo \
  --output /tmp/permeant-complex-agent-graph
```

Local export/import validation passed before the AWS run. The package contained:

| Field | Value |
| --- | ---: |
| Graph ID | `graph:complex-agent:0001` |
| Graph hash | `sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b` |
| Nodes | 27 |
| Edges | 25 |
| Message nodes | 9 |
| Tool-call nodes | 4 |
| Tool-result nodes | 1 |
| Artifact nodes | 4 |
| Packaged artifact files | 4 |
| Memory nodes | 2 |
| Retrieval nodes | 2 |
| Credential refs | 1 |
| KV spans | 1 |

The four packaged artifacts were:

| Artifact | SHA-256 |
| --- | --- |
| `reports/result.json` | `sha256:fa05654a9e30177f147ca503762c4faab330ccef3c746fb21a119c9c1c8094fd` |
| `reports/research/plan.json` | `sha256:a1a9630bbdc5fc8bbacd292b021a250eff43635813af4727f729483768c368cb` |
| `reports/audit/retrieval.json` | `sha256:050653f12ba49038bd9a6c51626da71d00e3ed7130e628a02d773fe0625e2184` |
| `reports/context/notes.md` | `sha256:c03fb00b4a5cb82cccecb6d8e43b0146e2f753b6f41f5e270c6d2cc453cd7a55` |

The tool policy mix included completed no-replay writes, a retry-safe pending
read-only call, and a pending external write that requires user approval before
resume. The credential reference required external rebinding rather than
embedding a secret.

## AWS Run

The real-runtime run used:

```bash
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-complex-agent-graph/manifest.json \
  scripts/aws-real-runtime-e2e.sh preflight

PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-complex-agent-graph/manifest.json \
  scripts/aws-real-runtime-e2e.sh run
```

| Field | Value |
| --- | --- |
| Preflight run ID | `20260620-165327` |
| AWS run ID | `20260620-165344` |
| Migration manifest | `migration-20260620-170130-37116-manifest.json` |
| Source runtime | local MLX exporter on Apple Silicon |
| Target runtime | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 2016 tokens |
| Transfer quantization | `none` |
| Layers written | 24 |
| Transferred bytes | 50,331,648 |
| Transfer time | 71,568.635 ms |
| Total migration time | 426,187.141 ms |
| Effective bandwidth | 0.005626112414656161 Gbps |

## Validation Evidence

The committed migration manifest reported:

- `success: true`
- `phase_status: committed`
- `agent_graph.graph_hash:
  sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b`
- one bound graph/KV span covering 998 graph prompt tokens
- all four artifact hashes preserved in the migration manifest

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
- `vllm_prefix_cache_seeded_block_count: 16`
- exact source/post-migration match for the configured 16 generated tokens

The slot-probe summary reported:

- `all_layers_slot_probe_match: true`
- `slot_probe_failure_count: 0`
- `max_key_abs_diff: 5.000000025123796e-09`
- `max_value_abs_diff: 5.000000025123796e-09`

The tiny non-zero slot deltas are below the validation tolerance and are
consistent with floating-point serialization/probe precision rather than a
failed slot write. The strict assertion used for this raw run accepted a
maximum sampled delta below `1e-6`.

## Cleanup

The runner cleanup completed at `2026-06-20T17:13:38Z`. Independent AWS sweeps
after the script exited returned empty result sets for:

- active/stopped EC2 instances tagged `Project=permeant-os`;
- `permeantos-real-e2e-*` security groups;
- `permeantos-real-e2e-*` key pairs.

The local MLX exporter was stopped and port `29101` was no longer listening.

## Conclusion

For the validated configuration, PermeantOS can move a graph-attached agent:
live MLX KV state, a complex Agent Memory Graph package, artifacts, memory,
retrieval evidence, credential rebinding requirements, and pending tool policies
were bound into one migration transaction, committed on a real AWS vLLM target,
and resumed with exact 16-token continuation fidelity.

This is not yet a universal production claim for every runtime, model, graph
shape, or longer continuation horizon. It is a concrete real-runtime proof that
agents can move on the current MLX-to-vLLM path.
