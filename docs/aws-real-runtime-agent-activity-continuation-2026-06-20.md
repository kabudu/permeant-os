# AWS Real-Runtime Agent Activity Continuation - 2026-06-20

This checkpoint validates agent-level continuation on the same disposable AWS
target used for real KV migration. It combines two proofs in one E2E run:

1. live MLX-to-vLLM KV migration with QATQ transfer compression; and
2. target-side Agent Memory Graph resume after migration, including new
   post-import tool activity and artifact generation.

This is stronger than token continuation alone. The migration first proves that
the live target runtime consumed migrated KV state. The target then imports the
same complex Agent Memory Graph package, resumes policy-governed pending work,
writes a new post-migration artifact, appends new graph activity evidence, and
emits a proof hash from the AWS host.

## Run Configuration

```bash
PERMEANT_TRANSFER_QUANTIZATION=qatq \
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-aws-agent-activity-package/manifest.json \
PERMEANT_AGENT_ACTIVITY_RESUME=1 \
PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH=1 \
  scripts/aws-real-runtime-e2e.sh run
```

| Field | Value |
| --- | --- |
| AWS run ID | `20260620-183853` |
| Migration manifest | `migration-20260620-184608-67621-manifest.json` |
| Source runtime | local MLX exporter on Apple Silicon |
| Target runtime | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 2016 tokens |
| Transfer quantization | `qatq` |
| Agent Memory Graph | complex 27-node package |
| Pre-resume graph hash | `sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b` |
| Git commit | `c389847` |

## Migration Fidelity

The migration committed successfully:

- `success: true`
- `phase_status: committed`
- `transfer_quantization: qatq`
- `uncompressed_bytes: 49,545,216`
- `transferred_bytes: 6,294,528`
- `compression_ratio: 0.12704613095238096`
- `transfer_time_ms: 62,659.609041`
- `commit_time_ms: 315,728.822916`
- `total_time_ms: 389,836.2535`

The fidelity analyzer reported:

- `matches_source_exactly: true`
- `matches_target_baseline_exactly: true`
- `migrated_decode_attachment_supported: true`
- `vllm_prefix_cache_seed_success: true`
- `vllm_prefix_cache_seeded_block_count: 16`
- `alignment.overall_status: aligned`
- `alignment.graph.status: aligned`
- `alignment.kv.status: aligned`
- `alignment.prompt.status: aligned`
- exact source/post-migration continuation for the configured 16 generated
  tokens

Expected QATQ lossy slot-probe deltas were present:

- `all_layers_slot_probe_match: false`
- `slot_probe_failure_count: 17`
- `max_key_abs_diff: 0.006696999999999065`
- `max_value_abs_diff: 0.000558149999999813`

## Target-Side Agent Activity Resume

After the migration and fidelity analysis, the runner executed the Agent Memory
Graph resume proof on the AWS target host.

The target-side resume report returned:

```json
{
  "status": "continued",
  "activity_continued": true,
  "publish_approved": true,
  "pre_resume_graph_hash": "sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b",
  "post_resume_graph_hash": "sha256:f338313bf4876e92f3b31e07f9790e46629f1e8d01d8e93930a01e63c1eab7c8",
  "proof_hash": "sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c"
}
```

Executed post-import tool calls:

- `tool:call:read-aws-quota`: completed retry-safe read-only
  `aws.ec2.describe_instances` simulation.
- `tool:call:publish-release`: completed explicitly approved
  `fs.write_file` publish action.

Written post-import artifact:

- `reports/publish/announcement.md`
- hash: `sha256:374424754eb8fa627048cb5b6a4c4b755abde3114f6fd55c99212dfe57689269`
- size: 567 bytes

Collected target artefacts:

- `.permeant-e2e/aws/20260620-183853/agent-activity-resume-report.json`
- `.permeant-e2e/aws/20260620-183853/agent-activity-resumed-graph.json`
- `.permeant-e2e/aws/20260620-183853/fidelity-analysis.json`
- `.permeant-e2e/aws/20260620-183853/fidelity-horizons.json`
- `.permeant-e2e/aws/20260620-183853/slot-probe-summary.json`

## Cleanup

The runner terminated the EC2 instance, deleted the temporary security group,
deleted the temporary key pair, and verified cleanup. Independent sweeps after
the run returned empty result sets for:

- active/stopped EC2 instances tagged `Project=permeant-os`;
- `permeantos-real-e2e-*` security groups;
- `permeantos-real-e2e-*` key pairs.

The local MLX exporter was stopped and port `29101` was no longer listening.

## Conclusion

For this validated configuration, PermeantOS has now demonstrated both forms of
continuation on a real AWS target:

- runtime continuation: migrated KV state was attached to vLLM prefix-cache
  state and produced exact 16-token source/post-migration decode fidelity; and
- agent activity continuation: the same complex Agent Memory Graph package was
  imported on the AWS target, resumed pending work, executed approved tool
  activity, wrote a new artifact, appended new graph evidence, and emitted a
  proof hash.

This is still scoped evidence. It covers one model family, one source runtime,
one AWS target runtime, one short continuation horizon, and a deterministic
Agent Memory Graph resume harness. Longer horizons, broader model/runtime
coverage, and durable target-side graph session storage remain required before
production claims.
