# AWS Real-Runtime Round-Trip Continuation Proof - 2026-06-20

This run proves Agent Memory Graph round-trip continuity for the validated
PermeantOS configuration:

1. origin local Apple Silicon MLX source exported live KV state and a complex
   Agent Memory Graph package;
2. AWS `g4dn.xlarge` vLLM target imported the migrated KV state and graph;
3. target-side vLLM continuation matched the source for the configured
   16-token horizon;
4. the AWS target resumed pending graph activity and wrote a new artifact;
5. the origin imported the AWS-updated graph/report/artifact evidence and
   wrote a new origin-side continuation artifact that depends on the AWS proof.

This is a graph/artifact/activity round trip. It does not yet prove reverse
live KV import from vLLM back into MLX; that remains a separate runtime-adapter
milestone.

## Command

```bash
PERMEANT_TRANSFER_QUANTIZATION=qatq \
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-aws-roundtrip-package/manifest.json \
PERMEANT_AGENT_ACTIVITY_RESUME=1 \
PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH=1 \
PERMEANT_AGENT_ACTIVITY_RETURN_HOME=1 \
scripts/aws-real-runtime-e2e.sh run
```

## Run Metadata

| Field | Value |
| --- | --- |
| AWS run ID | `20260620-202425` |
| Migration manifest | `migration-20260620-203118-94994-manifest.json` |
| Commit copied to target | `9fed3e4` |
| Source runtime | local MLX exporter on Apple Silicon |
| Target runtime | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 2016 tokens |
| Transfer quantization | experimental `qatq` |
| Agent Memory Graph | 27 nodes, 25 edges, 4 packaged artifacts |

## Migration Result

- phase status: `committed`
- hash validation: passed
- transferred bytes: `6,294,528`
- uncompressed bytes: `49,545,216`
- compression ratio: `0.12704613095238096`
- transfer time: `63,225.337625 ms`
- commit time: `308,381.092875 ms`
- total migration time: `383,115.057833 ms`
- effective bandwidth: `0.000796456387448196 Gbps`
- chunks sent: `384`

## Runtime Fidelity

- `matches_source_exactly: true`
- `matches_target_baseline_exactly: true`
- `migrated_decode_attachment_supported: true`
- `vllm_prefix_cache_seed_success: true`
- `vllm_prefix_cache_seeded_block_count: 16`
- exact horizon: 16 generated tokens

Expected QATQ lossy slot-probe deltas were present:

- `all_layers_slot_probe_match: false`
- `slot_probe_failure_count: 24`
- `max_key_abs_diff: 0.008929999999999438`
- `max_value_abs_diff: 0.0016742499999997662`

The QATQ claim remains bounded lossy compression with exact observed decode
fidelity over the configured horizon, not numerical losslessness.

## AWS Target Activity Proof

The AWS target imported the graph package and continued work:

```json
{
  "status": "continued",
  "activity_continued": true,
  "pre_resume_graph_hash": "sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b",
  "post_resume_graph_hash": "sha256:f338313bf4876e92f3b31e07f9790e46629f1e8d01d8e93930a01e63c1eab7c8",
  "proof_hash": "sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c"
}
```

Target-side work:

- completed retry-safe read-only quota work;
- executed explicitly approved publish work;
- wrote `reports/publish/announcement.md`;
- artifact hash:
  `sha256:374424754eb8fa627048cb5b6a4c4b755abde3114f6fd55c99212dfe57689269`.

## Origin Return-Home Proof

The origin then verified the AWS-updated graph/report/artifact and continued
from that returned state:

```json
{
  "status": "round_trip_continued",
  "round_trip_continued": true,
  "origin_pre_graph_hash": "sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b",
  "target_post_graph_hash": "sha256:f338313bf4876e92f3b31e07f9790e46629f1e8d01d8e93930a01e63c1eab7c8",
  "origin_post_graph_hash": "sha256:35d2b4c784a1243604140b2d017343140fefb8ed3b2722952c8d05a99ba732f8",
  "target_proof_hash": "sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c",
  "target_artifact_hash": "sha256:374424754eb8fa627048cb5b6a4c4b755abde3114f6fd55c99212dfe57689269",
  "proof_hash": "sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d"
}
```

Origin-side work:

- verified the target resume report proof hash;
- verified the returned graph hash;
- verified the AWS-written artifact bytes against the target report;
- wrote `reports/roundtrip/origin-continuation.md`;
- origin artifact hash:
  `sha256:5e8c88bf06ee7e1cffc5b51c34effc4d9d97bb6efd3e7e831de70d216611f4a8`.

The origin continuation artifact explicitly references the target post-resume
graph hash, target proof hash, and target artifact hash. That dependency is the
evidence that origin-side work continued from the AWS-produced state rather than
from the stale pre-migration origin graph.

## Evidence Files

- `.permeant-e2e/aws/20260620-202425/fidelity-analysis.json`
- `.permeant-e2e/aws/20260620-202425/fidelity-horizons.json`
- `.permeant-e2e/aws/20260620-202425/slot-probe-summary.json`
- `.permeant-e2e/aws/20260620-202425/agent-activity-resume-report.json`
- `.permeant-e2e/aws/20260620-202425/agent-activity-resumed-graph.json`
- `.permeant-e2e/aws/20260620-202425/agent-activity-publish-announcement.md`
- `.permeant-e2e/aws/20260620-202425/origin-roundtrip-workspace/reports/roundtrip/roundtrip-report.json`
- `.permeant-e2e/aws/20260620-202425/origin-roundtrip-workspace/reports/roundtrip/returned-home-graph.json`
- `.permeant-e2e/aws/20260620-202425/origin-roundtrip-workspace/reports/roundtrip/origin-continuation.md`

## Cleanup

The runner deleted the disposable AWS resources:

- instance `i-0d502bec6b67ae774`
- security group `sg-04475f9efe63c94ca`
- key pair `permeantos-real-e2e-20260620-202425-key`

Independent cleanup sweeps confirmed:

- no tagged PermeantOS EC2 instances in pending/running/stopping/stopped state;
- no `permeantos-real-e2e-*` security groups;
- no `permeantos-real-e2e-*` key pairs;
- no local MLX exporter listening on port `29101`.

## Conclusion

For the validated configuration, PermeantOS now demonstrates:

- live origin-to-AWS KV migration;
- exact short-horizon target runtime continuation;
- AWS target-side Agent Memory Graph activity continuation;
- return of AWS-updated graph/artifact evidence to the origin;
- origin-side continuation that depends on the AWS-produced proof.

The next stronger runtime milestone is reverse live KV/state attachment from the
remote runtime back into the origin runtime.
