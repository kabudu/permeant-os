# AWS Real-Runtime Round-Trip Continuation Proof - 2026-06-20

This run proves bidirectional runtime and Agent Memory Graph round-trip
continuity for the validated PermeantOS configuration:

1. origin local Apple Silicon MLX source exported live KV state and a complex
   Agent Memory Graph package;
2. AWS `g4dn.xlarge` vLLM target imported the migrated KV state and graph;
3. target-side vLLM continuation matched the source for the configured
   16-token horizon;
4. the AWS target exported its post-migration decode boundary through the
   reverse runtime API;
5. the origin MLX runtime imported that target-advanced boundary, materialized
   origin KV state, and produced a new origin continuation;
6. the AWS target resumed pending graph activity and wrote a new artifact;
7. the origin imported the AWS-updated graph/report/artifact evidence and
   wrote a new origin-side continuation artifact that depends on the AWS proof.

The reverse runtime path is implemented as a canonical decode-boundary export
rather than a byte-for-byte GPU block copy. vLLM and MLX use different physical
KV layouts, so the portable contract is: export the target prompt/generated
token boundary with proof hashes, import that boundary into MLX, materialize
MLX-native KV state, and continue.

## Command

```bash
PERMEANT_TRANSFER_QUANTIZATION=qatq \
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-aws-roundtrip-package/manifest.json \
PERMEANT_AGENT_ACTIVITY_RESUME=1 \
PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH=1 \
PERMEANT_AGENT_ACTIVITY_RETURN_HOME=1 \
PERMEANT_REVERSE_RUNTIME_IMPORT=1 \
scripts/aws-real-runtime-e2e.sh run
```

## Run Metadata

| Field | Value |
| --- | --- |
| AWS run ID | `20260620-210358` |
| Migration manifest | `migration-20260620-211207-46427-manifest.json` |
| Commit copied to target | `cae2ef1` |
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
- transfer time: `65,928.329 ms`
- commit time: `308,240.088208 ms`
- total migration time: `389,327.437458 ms`
- effective bandwidth: `0.0007638025225847906 Gbps`
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
- `slot_probe_failure_count: 17`
- `max_key_abs_diff: 0.006696999999999065`
- `max_value_abs_diff: 0.000558149999999813`

The QATQ claim remains bounded lossy compression with exact observed decode
fidelity over the configured horizon, not numerical losslessness.

## Reverse Runtime Export/Import Proof

After target continuation, the runner called the live target receiver API:

```text
POST http://127.0.0.1:29100/export_reverse_runtime_state
```

The API returned target runtime state from the same vLLM process that performed
the migrated decode:

```json
{
  "status": "target_runtime_state_exported",
  "proof_hash": "sha256:cc27f81da25d629d36e5b680d8986acf385b867d334ce67515912f2fbc1cce2f",
  "generated_token_count": 16,
  "last_registered_hash": "sha256:752b47177c4c532507d41557f9c2079d59d7ae8c676281199e826a6636c76640",
  "prompt_token_count": 2016
}
```

The origin then posted that API response to the live MLX exporter
`/import-reverse-state` endpoint. MLX imported the target-generated decode
boundary, materialized MLX-native KV state for the 2032-token advanced prompt,
and generated a new origin continuation:

```json
{
  "status": "reverse_runtime_imported",
  "reverse_runtime_imported": true,
  "target_proof_hash": "sha256:cc27f81da25d629d36e5b680d8986acf385b867d334ce67515912f2fbc1cce2f",
  "target_prompt_token_count": 2016,
  "target_generated_token_count": 16,
  "origin_advanced_prompt_token_count": 2032,
  "origin_continuation_token_count": 16,
  "proof_hash": "sha256:a4f0c01e5d02c9a07d6ca34fb95ce2d60232ea0a5583f88f0c45e61ae6a638d7"
}
```

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

- `.permeant-e2e/aws/20260620-210358/fidelity-analysis.json`
- `.permeant-e2e/aws/20260620-210358/fidelity-horizons.json`
- `.permeant-e2e/aws/20260620-210358/slot-probe-summary.json`
- `.permeant-e2e/aws/20260620-210358/vllm-reverse-runtime-state.json`
- `.permeant-e2e/aws/20260620-210358/mlx-reverse-import-report.json`
- `.permeant-e2e/aws/20260620-210358/agent-activity-resume-report.json`
- `.permeant-e2e/aws/20260620-210358/agent-activity-resumed-graph.json`
- `.permeant-e2e/aws/20260620-210358/agent-activity-publish-announcement.md`
- `.permeant-e2e/aws/20260620-210358/origin-roundtrip-workspace/reports/roundtrip/roundtrip-report.json`
- `.permeant-e2e/aws/20260620-210358/origin-roundtrip-workspace/reports/roundtrip/returned-home-graph.json`
- `.permeant-e2e/aws/20260620-210358/origin-roundtrip-workspace/reports/roundtrip/origin-continuation.md`

## Cleanup

The runner deleted the disposable AWS resources:

- instance `i-082cdbbca11910f2b`
- security group `sg-02171e42a36e97f82`
- key pair `permeantos-real-e2e-20260620-210358-key`

Independent cleanup sweeps confirmed:

- no tagged PermeantOS EC2 instances in pending/running/stopping/stopped state;
- no `permeantos-real-e2e-*` security groups;
- no `permeantos-real-e2e-*` key pairs;
- no local MLX exporter listening on port `29101`.

## Conclusion

For the validated configuration, PermeantOS now demonstrates:

- live origin-to-AWS KV migration;
- exact short-horizon target runtime continuation;
- reverse vLLM-to-MLX runtime-state export/import and origin continuation;
- AWS target-side Agent Memory Graph activity continuation;
- return of AWS-updated graph/artifact evidence to the origin;
- origin-side continuation that depends on the AWS-produced proof.
